# UI style rules

- Use Cards for the overall management section, Subject for a grouping of
  documents and ZIM libraries (Subject card when describing the card type),
  and Documents for the reference files. Use Subject for assignment and
  filtering; do not label shared documents as personal.

- A card row with one or more child entries uses the existing muted red tint to
  distinguish populated cards from empty cards.
- In content entry lists, place the entry text above its actions. Put Edit below
  the text on the left and Delete on the right.
- Keep Edit and Delete buttons as neutral outline controls: primary text color,
  a gray border, and no filled background. Hovering or focusing Delete changes
  it to a warning-red fill. While a destructive confirmation is armed, keep its
  warning-red fill until it is completed or reset.
- Label destructive content actions Delete, not Remove.
- An armed confirmation that receives no follow-up action returns to its
  original label after five seconds. Refresh this timeout after each step in a
  multi-step confirmation.
- Render form selects as boxed fields with a right-facing accent chevron.
- Render expandable menu summaries with accent text and an accent chevron.
- The All Online Sources and All RSS Feeds card groups are an exception to the
  accent-text menu rule: use primary text, an accent chevron, no enclosing box,
  and subtle dividers so each heading feels connected to its entries.
