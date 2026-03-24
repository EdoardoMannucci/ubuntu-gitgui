"""
Data structures for the commit graph visualiser.

These are pure, immutable data containers — no Qt or GitPython dependencies.
The layout algorithm (graph_layout.py) populates them; the view reads them.

Coordinate conventions used by LineSegment:
  x  — lane index (0 = leftmost lane, 1 = next, …)
  y  — fraction of the cell height (0.0 = top edge, 0.5 = centre, 1.0 = bottom edge)
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CommitData:
    """Raw Git commit information extracted from a GitPython Commit object."""

    full_hash: str       # 40-char SHA-1
    short_hash: str      # first 7 characters
    message: str         # first line of the commit message only
    author: str          # author display name
    date: str            # formatted date string, e.g. "2024-03-15 10:42"
    parent_hashes: tuple[str, ...]  # full SHAs of parent commits (0 for root, 2+ for merges)


@dataclass(frozen=True)
class LineSegment:
    """A single directed line segment drawn within one graph table cell.

    The segment starts at (x1, y1) and ends at (x2, y2), both in the
    normalised coordinate space described above.  For example:

      Straight vertical lane:    x1 == x2, y1=0.0, y2=1.0
      Incoming line to node:     x1 == x2, y1=0.0, y2=0.5
      Outgoing to first parent:  x1 == x2, y1=0.5, y2=1.0
      Merge diverge:             x1 != x2, y1=0.5, y2=1.0
      Merge converge:            x1 != x2, y1=0.0, y2=0.5
    """

    x1: float   # start lane position
    y1: float   # start y (0.0 = top)
    x2: float   # end lane position
    y2: float   # end y (1.0 = bottom)
    color: str  # hex color string, e.g. "#89b4fa"


@dataclass(frozen=True)
class GraphRow:
    """All visual data needed to render one row of the commit graph table.

    Produced by the layout algorithm in graph_layout.py and consumed
    by CommitGraphModel / GraphDelegate in the view layer.
    """

    commit: CommitData          # the commit this row represents
    node_lane: int              # lane index where the commit circle is drawn
    node_color: str             # hex color of the commit circle
    lines: tuple[LineSegment, ...]  # line segments to draw in this cell
    n_lanes: int                # total active lanes in this row (for cell width)
