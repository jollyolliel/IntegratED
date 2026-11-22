# Fail the cold database connection fast, and show a loading page instead

Neon's serverless Postgres suspends compute after idle time and wakes on the
next connection attempt, which can take several seconds. Left to its
defaults, the very first request after a period of idleness would simply
hang inside the connection attempt for the full wake window, with the
request thread tied up and the user staring at a spinner with no feedback —
and on the gthread worker model this app runs, a slow wake can tie up a
meaningful fraction of the available request threads at once.

The decision is to make that cold connection fail fast — a short
`connect_timeout` — rather than let it block for the full wake, and to catch
the resulting connection error with a dedicated handler that rolls back the
session and returns a 503 with a `Retry-After` hint: a self-refreshing
loading page for a browser, a JSON status for an API call. The failed
connection attempt still triggers Neon's wake server-side, so a refresh or
two after seeing the loading page lands on the real response once the
database is up. The trade-off is a request that would have quietly
succeeded after a several-second wait now visibly fails once and asks the
client to retry — accepted because a fast, honest "starting up" beats a long
silent hang, and because failing fast frees the request thread instead of
holding it hostage to the wake.

Status: accepted.
