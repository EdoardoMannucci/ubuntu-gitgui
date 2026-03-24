"""
Commit Graph Widget — the central panel showing commit history.

Architecture
────────────
CommitGraphWidget   QWidget container
  └─ QTableView     standard table, non-editable, full-row selection
       ├─ CommitGraphModel   QAbstractTableModel — 5 columns
       │    Col 0  Graph     → empty display text; UserRole returns GraphRow
       │    Col 1  Message   → commit subject line
       │    Col 2  Author    → author.name
       │    Col 3  Date      → formatted datetime
       │    Col 4  Hash      → 7-char short SHA
       └─ GraphDelegate      QStyledItemDelegate for column 0 only

Painting (GraphDelegate.paint)
──────────────────────────────
For each row the delegate receives a GraphRow (via UserRole).

Cell dimensions:
    CELL_HEIGHT  = 26 px  (set as default section size on vertical header)
    LANE_WIDTH   = 20 px  (horizontal space per lane)
    NODE_RADIUS  =  5 px  (commit circle)
    LINE_WIDTH   =  2 px  (branch line)

Each LineSegment carries (x1, y1, x2, y2) in lane/fraction coordinates.
The delegate converts them to pixel coordinates:
    px = (x + 0.5) * LANE_WIDTH           (lane centre)
    py = y * CELL_HEIGHT + rect.top()     (fraction of cell height)
"""

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPoint,
    QPointF,
    QRect,
    QSize,
    Qt,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
)
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from src.models.commit_graph import CommitData, GraphRow
from src.utils.graph_layout import compute_layout
from src.utils.icons import icon as get_icon

# ── Visual constants ──────────────────────────────────────────────────────────

CELL_HEIGHT: int = 26        # row height in pixels
LANE_WIDTH: int = 20         # horizontal pixels per lane column
NODE_RADIUS: float = 5.5     # radius of the commit circle in pixels
GLOW_RADIUS: float = 7.5     # semi-transparent outer glow ring radius
LINE_WIDTH: int = 2          # branch line thickness in pixels
GRAPH_PADDING: int = 6       # extra right-padding added to graph column

# Custom item data role for passing GraphRow objects to the delegate
_GRAPH_ROW_ROLE = Qt.ItemDataRole.UserRole

# Column indices
_COL_GRAPH   = 0
_COL_MESSAGE = 1
_COL_AUTHOR  = 2
_COL_DATE    = 3
_COL_HASH    = 4

_COLUMN_HEADERS = ("Graph", "Message", "Author", "Date", "Hash")
_FIXED_COL_WIDTHS = {
    _COL_AUTHOR: 160,
    _COL_DATE:   130,
    _COL_HASH:    75,
}


# ── CommitGraphModel ──────────────────────────────────────────────────────────

class CommitGraphModel(QAbstractTableModel):
    """Table model backed by a list of pre-computed GraphRow objects."""

    def __init__(
        self,
        rows: list[GraphRow],
        tags_by_hash: dict[str, list[str]] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._rows: list[GraphRow] = rows
        self._max_lanes: int = max((r.n_lanes for r in rows), default=1)
        self._tags_by_hash: dict[str, list[str]] = tags_by_hash or {}

    # ── Required overrides ────────────────────────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else 5

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if not index.isValid() or index.row() >= len(self._rows):
            return None

        row: GraphRow = self._rows[index.row()]
        col: int = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == _COL_GRAPH:   return ""   # painted by delegate, no text
            if col == _COL_MESSAGE:
                tags = self._tags_by_hash.get(row.commit.full_hash, [])
                prefix = "".join(f"[{t}] " for t in tags)
                return f"{prefix}{row.commit.message}" if prefix else row.commit.message
            if col == _COL_AUTHOR:  return row.commit.author
            if col == _COL_DATE:    return row.commit.date
            if col == _COL_HASH:    return row.commit.short_hash

        if role == _GRAPH_ROW_ROLE and col == _COL_GRAPH:
            return row  # the full GraphRow for the custom delegate

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == _COL_HASH:
                return QBrush(QColor("#474658"))   # outline_variant — dim hash
            if col == _COL_DATE:
                return QBrush(QColor("#aba9be"))   # on_surface_variant

        if role == Qt.ItemDataRole.FontRole:
            if col == _COL_HASH:
                font = QFont()
                font.setFamily("JetBrains Mono, Fira Code, Ubuntu Mono, monospace")
                font.setPointSize(10)
                return font

        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        return None

    def headerData(  # type: ignore[override]
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return _COLUMN_HEADERS[section]
        return None

    # ── Accessors used by CommitGraphWidget ───────────────────────────

    @property
    def max_lanes(self) -> int:
        """Maximum concurrent lane count across all rows."""
        return self._max_lanes

    def graph_column_width(self) -> int:
        """Suggested pixel width for the graph column."""
        return self._max_lanes * LANE_WIDTH + GRAPH_PADDING * 2


# ── GraphDelegate ─────────────────────────────────────────────────────────────

class GraphDelegate(QStyledItemDelegate):
    """Paints the graph column (col 0) with lines and commit circles."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        # Retrieve the GraphRow data attached to this cell
        graph_row: GraphRow | None = index.data(_GRAPH_ROW_ROLE)
        if graph_row is None:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect: QRect = option.rect
        cell_h: float = rect.height()
        top: float = rect.top()
        left: float = rect.left()

        # ── Background ────────────────────────────────────────────────
        if option.state & option.state.State_Selected:  # type: ignore[attr-defined]
            painter.fillRect(rect, QColor("#1d1e32"))
        else:
            painter.fillRect(rect, QColor("#0d0d1c"))

        # ── Line segments ─────────────────────────────────────────────
        for seg in graph_row.lines:
            px1 = left + GRAPH_PADDING + (seg.x1 + 0.5) * LANE_WIDTH
            py1 = top  + seg.y1 * cell_h
            px2 = left + GRAPH_PADDING + (seg.x2 + 0.5) * LANE_WIDTH
            py2 = top  + seg.y2 * cell_h

            pen = QPen(QColor(seg.color), LINE_WIDTH)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawLine(QPointF(px1, py1), QPointF(px2, py2))

        # ── Commit node — glow ring + filled circle ───────────────────
        node_x = left + GRAPH_PADDING + (graph_row.node_lane + 0.5) * LANE_WIDTH
        node_y = top  + cell_h * 0.5
        node_color = QColor(graph_row.node_color)

        # Outer glow ring (semi-transparent)
        glow_color = QColor(node_color)
        glow_color.setAlpha(22)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow_color))
        painter.drawEllipse(QPointF(node_x, node_y), GLOW_RADIUS, GLOW_RADIUS)

        # Inner filled circle with slight border
        border_color = node_color.lighter(140)
        painter.setPen(QPen(border_color, 1.2))
        painter.setBrush(QBrush(node_color))
        painter.drawEllipse(QPointF(node_x, node_y), NODE_RADIUS, NODE_RADIUS)

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        graph_row: GraphRow | None = index.data(_GRAPH_ROW_ROLE)
        if graph_row is not None:
            w = graph_row.n_lanes * LANE_WIDTH + GRAPH_PADDING * 2
        else:
            w = LANE_WIDTH + GRAPH_PADDING * 2
        return QSize(w, CELL_HEIGHT)


# ── CommitGraphWidget ─────────────────────────────────────────────────────────

class CommitGraphWidget(QWidget):
    """Public-facing widget that hosts the commit history table.

    MainWindow creates one instance and calls ``populate()`` / ``clear()``
    in response to repository lifecycle signals from RepositoryController.

    Pagination
    ──────────
    populate(commits, has_more)  — replace all rows; show "Load more" if has_more.
    append_commits(commits, has_more) — extend the list without resetting.
    load_more_requested(int)     — signal emitted with current count as skip offset.
    """

    load_more_requested     = pyqtSignal(int)    # payload: current count (skip offset)
    checkout_hash_requested = pyqtSignal(str)   # payload: full commit hash
    commit_selected         = pyqtSignal(object) # payload: CommitData | None
    create_tag_requested    = pyqtSignal(str)   # payload: full commit hash

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._delegate = GraphDelegate(self)
        self._loaded_commits: list[CommitData] = []
        self._tags_by_hash: dict[str, list[str]] = {}
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Empty-state placeholder ───────────────────────────────
        self._placeholder = QLabel(
            "Commit graph will appear here\n\n"
            "Open or clone a repository to get started."
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setObjectName("placeholder_label")
        layout.addWidget(self._placeholder)

        # ── Table view ────────────────────────────────────────────
        self._table = QTableView(self)
        self._table.setObjectName("commit_table")
        self._table.hide()

        # Behaviour
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)

        # Vertical header (row numbers) — hide it
        vh = self._table.verticalHeader()
        vh.setVisible(False)
        vh.setDefaultSectionSize(CELL_HEIGHT)
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

        # Horizontal header
        hh = self._table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setStretchLastSection(False)

        # Custom delegate for the graph column
        self._table.setItemDelegateForColumn(_COL_GRAPH, self._delegate)

        # Right-click context menu
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_table_context_menu)

        layout.addWidget(self._table)

        # ── "Load more" button (pagination) ───────────────────────
        self._load_more_btn = QPushButton("↓  Load more commits")
        self._load_more_btn.setObjectName("load_more_btn")
        self._load_more_btn.hide()
        self._load_more_btn.clicked.connect(
            lambda: self.load_more_requested.emit(len(self._loaded_commits))
        )
        layout.addWidget(self._load_more_btn)

    # ── Public API ────────────────────────────────────────────────────

    def populate(
        self,
        commits: list[CommitData],
        has_more: bool = False,
        tags_by_hash: dict[str, list[str]] | None = None,
    ) -> None:
        """Replace all rows and display the first page of commit history.

        Args:
            commits:      Ordered list (newest first) from RepositoryController.
            has_more:     True if more commits exist beyond this page.
            tags_by_hash: Optional {full_hash: [tag_name, ...]} mapping for
                          tag badges in the Message column.
        """
        self._loaded_commits = list(commits)
        self._tags_by_hash = tags_by_hash or {}
        self._render(has_more)

    def append_commits(
        self,
        new_commits: list[CommitData],
        has_more: bool = False,
    ) -> None:
        """Extend the commit list with the next page and re-render.

        Args:
            new_commits: Additional commits to append (newest-first within the page).
            has_more:    True if even more commits exist beyond this page.
        """
        self._loaded_commits.extend(new_commits)
        self._render(has_more)

    def clear(self) -> None:
        """Remove all commit data and show the empty-state placeholder."""
        self._loaded_commits = []
        self._table.setModel(None)
        self._table.hide()
        self._load_more_btn.hide()
        self._show_placeholder(
            "Commit graph will appear here\n\n"
            "Open or clone a repository to get started."
        )

    # ── Context menu ──────────────────────────────────────────────────

    def _on_table_context_menu(self, pos) -> None:
        """Show a context menu for the commit row at *pos*."""
        index = self._table.indexAt(pos)
        if not index.isValid():
            return

        row = index.row()
        model = self._table.model()
        if model is None or row >= len(self._loaded_commits):
            return

        commit = self._loaded_commits[row]
        short  = commit.short_hash
        full   = commit.full_hash

        menu = QMenu(self)

        checkout_act = menu.addAction(
            get_icon("checkout_detached"),
            f"Checkout '{short}' (detached HEAD)",
        )
        menu.addSeparator()
        copy_short_act = menu.addAction(
            get_icon("copy_hash"), f"Copy Short Hash  ({short})"
        )
        copy_full_act = menu.addAction(
            get_icon("copy_hash"), f"Copy Full Hash   ({full[:12]}…)"
        )
        menu.addSeparator()
        create_tag_act = menu.addAction(
            get_icon("tag"), f"Create Tag Here…"
        )

        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))

        if chosen == checkout_act:
            self.checkout_hash_requested.emit(full)
        elif chosen == copy_short_act:
            QApplication.clipboard().setText(short)
        elif chosen == copy_full_act:
            QApplication.clipboard().setText(full)
        elif chosen == create_tag_act:
            self.create_tag_requested.emit(full)

    # ── Private helpers ───────────────────────────────────────────────

    def _render(self, has_more: bool) -> None:
        """Recompute the layout for all loaded commits and refresh the table."""
        if not self._loaded_commits:
            self._show_placeholder("Repository has no commits yet.")
            self._load_more_btn.hide()
            self.commit_selected.emit(None)
            return

        rows = compute_layout(self._loaded_commits)

        model = CommitGraphModel(rows, tags_by_hash=self._tags_by_hash, parent=self)
        self._table.setModel(model)

        # Reconnect the selection model every time the model is replaced
        self._table.selectionModel().currentRowChanged.connect(
            self._on_current_row_changed
        )

        hh = self._table.horizontalHeader()
        # All columns are user-resizable (Interactive); Message stretches by default
        hh.setSectionResizeMode(_COL_GRAPH,   QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(_COL_MESSAGE, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(_COL_AUTHOR,  QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(_COL_DATE,    QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(_COL_HASH,    QHeaderView.ResizeMode.Interactive)

        self._table.setColumnWidth(_COL_GRAPH, model.graph_column_width())
        for col, width in _FIXED_COL_WIDTHS.items():
            self._table.setColumnWidth(col, width)

        self._table.show()
        self._placeholder.hide()

        if has_more:
            self._load_more_btn.show()
        else:
            self._load_more_btn.hide()

    def _on_current_row_changed(self, current, _previous) -> None:
        """Emit commit_selected when the user moves to a different row."""
        row = current.row()
        if 0 <= row < len(self._loaded_commits):
            self.commit_selected.emit(self._loaded_commits[row])
        else:
            self.commit_selected.emit(None)

    def _show_placeholder(self, text: str) -> None:
        self._placeholder.setText(text)
        self._placeholder.show()
        self._table.hide()
