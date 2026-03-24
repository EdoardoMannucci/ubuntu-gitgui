"""
Graph layout algorithm — converts a flat list of CommitData into GraphRows.

Algorithm overview
──────────────────
We process commits in reverse-chronological / topological order (newest
first), which is the order returned by ``git rev-list --all --topo-order``.
We maintain a list of **active lanes**:

    active: list[tuple[str, str] | None]

Each slot is either ``(expected_hash, color)`` — meaning "this lane is
currently 'open' waiting for the commit with that hash" — or ``None``
(the lane slot is free and can be reused).

For every commit C we:

  1. **Find converging lanes** — all slots whose expected hash equals C's hash.
     The first is ``my_lane``; additional ones are other branches that merge
     INTO this commit from above.

  2. **Assign a lane** — if C doesn't appear in any active slot, it is a new
     branch tip: allocate the first free slot (or append one).

  3. **Draw top-half segments** (y 0.0 → 0.5):
     - Each converging lane draws a line from its x-position to ``my_lane``.
     - ``my_lane`` itself draws a straight incoming line if it was already
       active (not a new tip).

  4. **Draw bottom-half segments** (y 0.5 → 1.0):
     - First parent continues straight in ``my_lane`` (or converges to an
       existing lane if the first parent is already tracked elsewhere).
     - Additional parents (merge branches) diverge to new or existing lanes.

  5. **Pass-through lanes** (y 0.0 → 1.0):
     All lanes that are active both before and after this commit, and are
     NOT involved in the commit, draw a straight vertical line through the
     whole cell.

  6. **Update ``active``**: free converging slots, assign parents.
"""

from src.models.commit_graph import CommitData, GraphRow, LineSegment


# ── Palette ───────────────────────────────────────────────────────────────────

LANE_COLORS: list[str] = [
    "#9cefff",  # primary   — neon cyan
    "#d1abfd",  # secondary — electric purple
    "#ffd3f2",  # tertiary  — soft pink
    "#8ee1f0",  # cyan variant
    "#c39eee",  # purple variant
    "#fab387",  # peach
    "#f9e2af",  # amber
    "#94e2d5",  # teal
    "#a6e3a1",  # green
    "#eba0ac",  # rose
]

# ── Internal type alias ───────────────────────────────────────────────────────

# A lane slot: either (commit_hash, hex_color) or None (free)
_Slot = tuple[str, str] | None
_Active = list[_Slot]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _first_free(active: _Active) -> int:
    """Return the index of the first free (None) slot, or len(active) if none."""
    for i, slot in enumerate(active):
        if slot is None:
            return i
    return len(active)


def _find_hash(active: _Active, commit_hash: str) -> list[int]:
    """Return all lane indices whose expected hash matches *commit_hash*."""
    return [i for i, slot in enumerate(active) if slot is not None and slot[0] == commit_hash]


def _trim(active: _Active) -> None:
    """Remove trailing None entries in-place."""
    while active and active[-1] is None:
        active.pop()


# ── Main algorithm ────────────────────────────────────────────────────────────

def compute_layout(commits: list[CommitData]) -> list[GraphRow]:
    """Compute the visual lane layout for a list of commits.

    Args:
        commits: Commits in reverse-topological order (newest first).
                 Typically produced by ``RepositoryController.load_commits()``.

    Returns:
        One ``GraphRow`` per commit, in the same order as the input list.
    """
    active: _Active = []
    color_counter: int = 0
    rows: list[GraphRow] = []

    for commit in commits:
        h: str = commit.full_hash
        parents: tuple[str, ...] = commit.parent_hashes

        # ── Step 1: find all lanes converging at this commit ──────────
        converging: list[int] = _find_hash(active, h)

        # ── Step 2: determine my_lane and node_color ──────────────────
        if converging:
            my_lane: int = converging[0]
            node_color: str = active[my_lane][1]  # type: ignore[index]
        else:
            # New branch tip — allocate first free slot
            my_lane = _first_free(active)
            if my_lane == len(active):
                active.append(None)
            node_color = LANE_COLORS[color_counter % len(LANE_COLORS)]
            color_counter += 1

        # ── Step 3: collect line segments ─────────────────────────────
        segments: list[LineSegment] = []

        # Pass-through lanes: active slots that are NOT this commit
        for i, slot in enumerate(active):
            if slot is None or slot[0] == h:
                continue  # skip free slots and lanes converging here
            segments.append(LineSegment(x1=i, y1=0.0, x2=i, y2=1.0, color=slot[1]))

        # Top-half incoming to node:
        if converging:
            # my_lane's own incoming line (straight down to centre)
            segments.append(
                LineSegment(x1=my_lane, y1=0.0, x2=my_lane, y2=0.5, color=node_color)
            )
            # Other converging lanes sweep diagonally to my_lane
            for conv in converging:
                if conv != my_lane:
                    conv_color: str = active[conv][1]  # type: ignore[index]
                    segments.append(
                        LineSegment(x1=conv, y1=0.0, x2=my_lane, y2=0.5, color=conv_color)
                    )
        # else: new branch tip — no incoming line, node appears at the top

        # ── Step 4: build the new active state ────────────────────────
        new_active: _Active = list(active)

        # Free ALL converging lanes (they are "consumed" by this commit)
        for conv in converging:
            new_active[conv] = None

        # Assign parents
        if parents:
            p0 = parents[0]

            # Check if first parent is ALREADY tracked in another lane
            # (happens when two independent branches share the same parent)
            existing_p0 = next(
                (i for i, s in enumerate(new_active) if s is not None and s[0] == p0),
                -1,
            )

            if existing_p0 != -1:
                # First parent already tracked → draw convergence line and free my_lane
                p0_color: str = new_active[existing_p0][1]  # type: ignore[index]
                segments.append(
                    LineSegment(x1=my_lane, y1=0.5, x2=existing_p0, y2=1.0, color=p0_color)
                )
                # my_lane stays None (already freed above)
            else:
                # First parent takes my_lane (normal continuation)
                new_active[my_lane] = (p0, node_color)
                segments.append(
                    LineSegment(x1=my_lane, y1=0.5, x2=my_lane, y2=1.0, color=node_color)
                )

            # Additional parents (merge commit: 2+ parents)
            for extra_p in parents[1:]:
                # Check if already tracked somewhere
                existing_extra = next(
                    (i for i, s in enumerate(new_active) if s is not None and s[0] == extra_p),
                    -1,
                )
                if existing_extra != -1:
                    # Already tracked → draw divergence to that lane
                    extra_color: str = new_active[existing_extra][1]  # type: ignore[index]
                    segments.append(
                        LineSegment(x1=my_lane, y1=0.5, x2=existing_extra, y2=1.0, color=extra_color)
                    )
                else:
                    # New lane for this parent
                    free_slot = _first_free(new_active)
                    if free_slot == len(new_active):
                        new_active.append(None)
                    extra_color = LANE_COLORS[color_counter % len(LANE_COLORS)]
                    color_counter += 1
                    new_active[free_slot] = (extra_p, extra_color)
                    segments.append(
                        LineSegment(x1=my_lane, y1=0.5, x2=free_slot, y2=1.0, color=extra_color)
                    )
        # else: root commit — no outgoing lines from the node

        _trim(new_active)

        # n_lanes = widest point covered by this row
        n_lanes: int = max(len(active), len(new_active), my_lane + 1)

        rows.append(
            GraphRow(
                commit=commit,
                node_lane=my_lane,
                node_color=node_color,
                lines=tuple(segments),
                n_lanes=n_lanes,
            )
        )

        active = new_active

    return rows
