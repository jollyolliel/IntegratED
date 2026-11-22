# Courses are bands on one placement scale, not separately placed subjects

The placement test ran one adaptive staircase per subject and recommended a
topic inside each one. The curriculum is moving to several courses for very
different learners: pre-literacy, phonics, everyday English, grammar. These
are not independent skills. They are stretches of one English ability, so
testing each course separately would ask a learner who can't yet read to sit
a grammar staircase, and would leave the choice of course to nobody.

The decision is that a course (a `Subject`) can sit on a **placement scale**.
A scale is a subject whose placement questions measure levels 1…N, usually a
placement-only one such as "English". The course declares the band of scale
levels it serves (`placement_scale_id`, `placement_min_level`,
`placement_max_level`). The test runs one staircase per scale, as before, so
`subject_levels` stays `{scale: level}`. The recommendation picks the course
whose band holds the level, then the topic inside it. On a banded course,
`Topic.level` is a level on the scale, not a rank inside the course. That
lets one comparison choose the starting topic, and lets several topics share
a level. The importer refuses bands that overlap, leave a scale level in no
course's band, or overrun the scale, so every level has exactly one course.

Rejected: an ordered list of courses with the placement level mapped onto
positions inside each one. It is less to write in the file, but a topic's
difficulty would then mean different things in different courses, and moving
a band would silently re-rank every topic in it. Also rejected: keeping
per-course staircases and picking the course with the "best" result. Levels
from different staircases can't be compared, and a beginner would sit every
course's test.

Consequences: courses without a band keep working unchanged, including the
older shape where a course's own placement questions name it. A scale with
courses on it can't also be a course. One staircase over the whole range
needs more placement questions per level than a short per-course test did;
the content doc sets the numbers.

Status: accepted.
