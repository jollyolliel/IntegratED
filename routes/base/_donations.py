import logging
from datetime import UTC, datetime

from flask import flash, redirect, request, url_for
from sqlalchemy.exc import IntegrityError

# Loaded on the first donation, not at app start: importing Stripe (with requests and asyncio
# under it) costs a noticeable slice of every cold start, and no other page needs it.
lazy import stripe

from extensions import db
from helpers.analytics import capture_event
from helpers.i18n import get_current_lang, make_translator
from helpers.programme_stats import programme_stats
from helpers.render import render_template
from models import Donation, School
from routes.base import base_bp
from settings import get_settings

logger = logging.getLogger(__name__)

#: Donation sizes with their own impact line (`donations.success_impact_<n>`); less is `_default`.
IMPACT_TIERS = (500, 250, 100, 50, 25)


def impact_tier(amount: float) -> str:
    """The impact line a donation of `amount` earns: the largest tier it reaches, else "default".

    Args:
        amount (float): The donation, in whole units.

    Returns:
        str: A tier such as "100", or "default".
    """
    return next((str(tier) for tier in IMPACT_TIERS if amount >= tier), "default")


def _impact_lines() -> list[tuple[int, str]]:
    """Every tier's translated impact line, largest first, for the form to pick from as the amount changes."""
    t = make_translator(get_current_lang())
    return [(tier, t(f"donations.success_impact_{tier}")) for tier in IMPACT_TIERS] + [
        (0, t("donations.success_impact_default"))
    ]


@base_bp.route("/donations")
def donations():
    """Public donation form page — no Stripe interaction yet (donations_submit does that).
    `?school=<id>` (a school page's donate button) preselects that school; otherwise the first."""
    capture_event(None, "page_viewed", properties={"page": "donations"})
    schools = db.session.scalars(db.select(School).order_by(School.name)).all()
    requested_id = request.args.get("school", type=int)
    selected = next((s for s in schools if s.id == requested_id), schools[0] if schools else None)
    return render_template(
        "@pages/donations.jx", stats=programme_stats(), schools=schools, selected=selected, impact_lines=_impact_lines()
    )


@base_bp.route("/donations", methods=["POST"])
def donations_submit():
    """Kicks off a Stripe Checkout session for a one-off donation."""
    # No Donation row is created here — donation_success() and stripe_webhook()
    # are the two paths that persist one, both via record_donation_from_session,
    # so a browser closed mid-checkout never leaves a stray unrecorded charge.
    # school/donor_name/message ride along as Stripe session metadata since by
    # success time only the Stripe session_id is available to look them up by.
    school = request.form.get("school", "").strip()
    amount_raw = request.form.get("amount", "").strip()
    donor_name = request.form.get("donor_name", "").strip()
    donor_email = request.form.get("donor_email", "").strip()
    message = request.form.get("message", "").strip()

    try:
        amount = float(amount_raw)
        if amount < 0.50:
            raise ValueError
    except (ValueError, TypeError):
        flash("Please select a valid donation amount (minimum $0.50).", "error")
        return redirect(url_for("base.donations"))

    if not school:
        flash("Please select a school.", "error")
        return redirect(url_for("base.donations"))

    if get_settings().is_preview:
        # English only, like the rest of the preview's own text: reviewers are its only readers.
        flash("Checkout is unavailable in a preview. Nothing was sent to Stripe.", "error")
        return redirect(url_for("base.donations"))

    capture_event(None, "donation_checkout_started", properties={
        "school": school,
        "amount": amount,
        "has_name": bool(donor_name),
        "has_email": bool(donor_email),
    })

    try:
        # No payment-method list: Checkout offers whatever the Stripe Dashboard
        # enables. stripe 16 renamed `payment_method_types` to
        # `allowed_payment_method_types`, so naming either ties this call to one
        # SDK major version.
        stripe.api_key = get_settings().stripe_secret_key or None
        session = stripe.checkout.Session.create(
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": round(amount * 100),
                    "product_data": {
                        "name": f"Donation to {school}",
                        "description": "Supporting refugee youth education through the IntegratED platform.",
                    },
                },
                "quantity": 1,
            }],
            mode="payment",
            submit_type="donate",
            # stripe-python's stub types this field as bare `str`, though it's
            # NotRequired and the real API accepts omitting it entirely.
            customer_email=donor_email if donor_email else None,  # ty: ignore[invalid-argument-type]
            metadata={
                "school": school,
                "donor_name": donor_name,
                "message": message,
            },
            success_url=url_for("base.donation_success", _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=url_for("base.donations", _external=True),
        )
        if not session.url:
            flash("Payment error: Stripe did not return a checkout URL.", "error")
            return redirect(url_for("base.donations"))
        return redirect(session.url, code=303)
    except stripe.StripeError as e:
        flash(f"Payment error: {e.user_message}", "error")
        return redirect(url_for("base.donations"))


def record_donation_from_session(stripe_session):
    """Create a Donation row from a completed Stripe Checkout Session.

    Idempotent on `stripe_session_id`. Called from both the Stripe webhook
    and the success-page fallback."""
    # `stripe_session` may be a StripeObject (no `.get()`) or a plain dict --
    # normalize to a dict so the lookups below work either way.
    if hasattr(stripe_session, "to_dict"):
        stripe_session = stripe_session.to_dict()

    session_id = stripe_session.get("id")
    if not session_id:
        return None

    if db.session.scalar(db.select(Donation).filter_by(stripe_session_id=session_id)):
        return None

    metadata = stripe_session.get("metadata") or {}
    school_name = metadata.get("school", "")
    school = db.session.scalar(db.select(School).filter_by(name=school_name))

    donation = Donation(
        stripe_session_id=session_id,
        amount=stripe_session.get("amount_total") or 0,
        donor_name=metadata.get("donor_name") or None,
        donor_email=(stripe_session.get("customer_details") or {}).get("email") or None,
        message=metadata.get("message") or None,
        # No school_name copy — resolve the name via school_id -> School at read time.
        school_id=school.id if school else None,
        status="completed",
        created_at=datetime.now(UTC),
    )
    db.session.add(donation)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None
    return donation


@base_bp.route("/donation-success")
def donation_success():
    """Stripe's success redirect. Records the donation as a dev-only fallback
    for when the webhook can't reach a local server."""
    # Idempotent on stripe_session_id, so this racing the real webhook is harmless.
    session_id = request.args.get("session_id")
    school = None
    amount = None
    if session_id:
        try:
            stripe.api_key = get_settings().stripe_secret_key or None
            session = stripe.checkout.Session.retrieve(session_id)
            metadata = session.metadata
            school = metadata.get("school") if isinstance(metadata, dict) else None
            amount = session.amount_total / 100 if session.amount_total else None
            if session.payment_status == "paid":
                record_donation_from_session(session)
            capture_event(None, "donation_completed", properties={
                "school": school,
                "amount": amount,
                "session_id": session_id,
            })
        except stripe.StripeError:
            # The thank-you page still renders, just without the amount; the webhook records the
            # donation either way.
            logger.warning("Donation success page could not read its Stripe session", exc_info=True)
    return render_template(
        "@pages/donation_success.jx", school=school, amount=amount, tier=impact_tier(amount) if amount else None
    )


@base_bp.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Authoritative donation-recording path. Verifies the Stripe signature
    before doing anything else."""
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    webhook_secret = get_settings().stripe_webhook_secret

    if not webhook_secret:
        return "", 400

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        return "", 400

    if event["type"] == "checkout.session.completed":
        record_donation_from_session(event["data"]["object"])

    return "", 200
