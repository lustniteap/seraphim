# Ratings from the web page

Each person's exported ratings go here as `feedback-<name>.jsonl` (one file per person, so several people
can add theirs without merge conflicts). In the web page, rate a set of engineer's notes with the thumbs,
then use **Export my ratings** under them; it saves the file to your Downloads.

A file has, for each rated set of notes, the measurements they were written from, the notes, the rating and
the reasons given. It never has audio or a file name, so it's safe to commit. Read the files with:

    python evals/notes_eval.py feedback

These are opinions on real bounces. They show what people find useful, and which kinds of mistake they notice,
but they don't replace the hand labels (`label` / `agreement`) that check the judge.
