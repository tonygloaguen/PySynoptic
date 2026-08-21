"""Native Tk Canvas renderer for positioned dependency graphs."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from typing import Any

import ttkbootstrap as ttk

from pysynoptic.graph import GraphLayout, GraphNode, PositionedNode

_BACKGROUND = "#f7f9fc"
_NODE_FILL = "#ffffff"
_NODE_OUTLINE = "#a8b2c1"
_EDGE = "#93a1b3"
_TEXT = "#263238"
_SELECTED = "#0d6efd"
_NEIGHBOR = "#dcecff"
_HIGHLIGHT_EDGE = "#0d6efd"
_MUTED = "#d7dde5"


class DependencyGraphCanvas(ttk.Frame):
    """Pan, zoom, fit, and select a pure ``GraphLayout`` on a Canvas."""

    def __init__(
        self,
        master: Any,
        *,
        on_select: Callable[[GraphNode], None] | None = None,
        on_activate: Callable[[GraphNode], None] | None = None,
        node_label: str = "modules",
        edge_label: str = "dependencies",
        empty_message: str = "Analyze a project to display its dependency graph.",
    ) -> None:
        super().__init__(master)
        self._layout: GraphLayout | None = None
        self._nodes: dict[str, PositionedNode] = {}
        self._node_items: dict[int, str] = {}
        self._selected_id: str | None = None
        self._scale = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._pan_anchor: tuple[float, float] | None = None
        self._on_select = on_select
        self._on_activate = on_activate
        self._node_label = node_label
        self._edge_label = edge_label
        self._empty_message = empty_message

        controls = ttk.Frame(self, padding=(0, 0, 0, 7))
        controls.pack(fill="x")
        ttk.Button(
            controls,
            text="−",
            width=3,
            command=lambda: self._zoom_at(0.8),
            bootstyle="secondary-outline",
        ).pack(side="left")
        ttk.Button(
            controls,
            text="+",
            width=3,
            command=lambda: self._zoom_at(1.25),
            bootstyle="secondary-outline",
        ).pack(side="left", padx=(5, 8))
        ttk.Button(
            controls,
            text="Fit",
            command=self.fit,
            bootstyle="primary-outline",
        ).pack(side="left")
        self.zoom_variable = ttk.StringVar(value="100%")
        ttk.Label(controls, textvariable=self.zoom_variable).pack(
            side="left", padx=(10, 0)
        )
        self.graph_status_variable = ttk.StringVar(value="No graph")
        ttk.Label(controls, textvariable=self.graph_status_variable).pack(side="right")

        self.canvas = tk.Canvas(
            self,
            background=_BACKGROUND,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#d7dde5",
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._pointer_down)
        self.canvas.bind("<Double-Button-1>", self._pointer_activate)
        self.canvas.bind("<B1-Motion>", self._pointer_drag)
        self.canvas.bind("<ButtonRelease-1>", self._pointer_up)
        self.canvas.bind("<ButtonPress-2>", self._pointer_down)
        self.canvas.bind("<B2-Motion>", self._pointer_drag)
        self.canvas.bind("<ButtonRelease-2>", self._pointer_up)
        self.canvas.bind("<MouseWheel>", self._mouse_wheel)
        self.canvas.bind("<Button-4>", lambda event: self._wheel_step(event, 1))
        self.canvas.bind("<Button-5>", lambda event: self._wheel_step(event, -1))
        self.after_idle(self._draw)

    @property
    def selected_node_id(self) -> str | None:
        """Return the currently selected node identifier."""
        return self._selected_id

    def set_layout(self, layout: GraphLayout) -> None:
        """Display a new layout and fit it to the current viewport."""
        self._layout = layout
        self._nodes = {item.node.node_id: item for item in layout.nodes}
        self._selected_id = None
        self._update_status()
        self.after_idle(self.fit)

    def clear(self) -> None:
        """Remove the current layout and reset navigation state."""
        self._layout = None
        self._nodes.clear()
        self._selected_id = None
        self._scale = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._draw()
        self._update_status()

    def fit(self) -> None:
        """Fit the complete graph inside the visible Canvas."""
        layout = self._layout
        if layout is None or not layout.nodes:
            self._draw()
            return
        canvas_width = max(self.canvas.winfo_width(), 200)
        canvas_height = max(self.canvas.winfo_height(), 160)
        padding = 24.0
        self._scale = max(
            0.2,
            min(
                1.6,
                (canvas_width - 2 * padding) / layout.width,
                (canvas_height - 2 * padding) / layout.height,
            ),
        )
        self._offset_x = (canvas_width - layout.width * self._scale) / 2
        self._offset_y = (canvas_height - layout.height * self._scale) / 2
        self._draw()

    def select_node(self, node_id: str, *, center: bool = False) -> bool:
        """Select a node, replacing earlier highlighting, if it exists."""
        if node_id not in self._nodes:
            return False
        self._selected_id = node_id
        if center:
            self._center_node(node_id)
        self._draw()
        self._update_status()
        return True

    def clear_selection(self) -> None:
        """Clear all node and neighborhood highlighting."""
        if self._selected_id is None:
            return
        self._selected_id = None
        self._draw()
        self._update_status()

    def activate_node(self, node_id: str) -> bool:
        """Select and activate a node through the double-click callback."""
        if not self.select_node(node_id):
            return False
        if self._on_activate is not None:
            self._on_activate(self._nodes[node_id].node)
        return True

    def _update_status(self) -> None:
        layout = self._layout
        if layout is None:
            message = "No graph"
        elif self._selected_id:
            message = self._nodes[self._selected_id].node.label
        else:
            message = (
                f"{len(layout.nodes)} {self._node_label} · "
                f"{len(layout.edges)} {self._edge_label}"
            )
        self.graph_status_variable.set(message)
        self.zoom_variable.set(f"{self._scale:.0%}")

    def _screen(self, x: float, y: float) -> tuple[float, float]:
        return (
            x * self._scale + self._offset_x,
            y * self._scale + self._offset_y,
        )

    def _screen_box(self, node: PositionedNode) -> tuple[float, float, float, float]:
        left, top = self._screen(node.x, node.y)
        right, bottom = self._screen(
            node.x + node.width,
            node.y + node.height,
        )
        return left, top, right, bottom

    @staticmethod
    def _boundary_point(
        source: PositionedNode, target: PositionedNode
    ) -> tuple[float, float]:
        source_x = source.x + source.width / 2
        source_y = source.y + source.height / 2
        target_x = target.x + target.width / 2
        target_y = target.y + target.height / 2
        delta_x = target_x - source_x
        delta_y = target_y - source_y
        factors = []
        if delta_x:
            factors.append((source.width / 2) / abs(delta_x))
        if delta_y:
            factors.append((source.height / 2) / abs(delta_y))
        factor = min(factors, default=0.0)
        return source_x + delta_x * factor, source_y + delta_y * factor

    def _edge_points(
        self, source: PositionedNode, target: PositionedNode
    ) -> tuple[float, ...]:
        if source.node.node_id == target.node.node_id:
            right = source.x + source.width
            top = source.y
            loop_width = 32.0
            loop_height = 25.0
            points = (
                (right, source.y + source.height * 0.65),
                (right + loop_width, source.y + source.height * 0.65),
                (right + loop_width, top - loop_height),
                (right - 12.0, top - loop_height),
                (right - 12.0, top),
            )
        else:
            points = (
                self._boundary_point(source, target),
                self._boundary_point(target, source),
            )
        return tuple(
            coordinate for point in points for coordinate in self._screen(*point)
        )

    def _highlight_sets(self) -> tuple[set[str], set[tuple[str, str]]]:
        if self._layout is None or self._selected_id is None:
            return set(), set()
        neighbors = {self._selected_id}
        edges: set[tuple[str, str]] = set()
        for edge in self._layout.edges:
            if self._selected_id in {edge.source_id, edge.target_id}:
                neighbors.update((edge.source_id, edge.target_id))
                edges.add((edge.source_id, edge.target_id))
        return neighbors, edges

    def _draw(self) -> None:
        self.canvas.delete("all")
        self._node_items.clear()
        layout = self._layout
        if layout is None or not layout.nodes:
            width = max(self.canvas.winfo_width(), 300)
            height = max(self.canvas.winfo_height(), 180)
            self.canvas.create_text(
                width / 2,
                height / 2,
                text=self._empty_message,
                fill="#6c757d",
                font=("TkDefaultFont", 11),
            )
            self._update_status()
            return

        highlighted_nodes, highlighted_edges = self._highlight_sets()
        has_selection = self._selected_id is not None
        for edge in layout.edges:
            source = self._nodes[edge.source_id]
            target = self._nodes[edge.target_id]
            edge_key = (edge.source_id, edge.target_id)
            highlighted = edge_key in highlighted_edges
            self.canvas.create_line(
                *self._edge_points(source, target),
                fill=(
                    _HIGHLIGHT_EDGE
                    if highlighted
                    else _MUTED
                    if has_selection
                    else _EDGE
                ),
                width=2.4 if highlighted else 1.4,
                arrow="last",
                arrowshape=(9, 11, 4),
                smooth=source.node.node_id == target.node.node_id,
            )

        font_size = max(3, min(13, round(10 * self._scale)))
        for positioned in layout.nodes:
            node_id = positioned.node.node_id
            selected = node_id == self._selected_id
            neighbor = node_id in highlighted_nodes
            muted = has_selection and not neighbor
            box = self._screen_box(positioned)
            rectangle = self.canvas.create_rectangle(
                *box,
                fill=_SELECTED if selected else _NEIGHBOR if neighbor else _NODE_FILL,
                outline=_MUTED if muted else _SELECTED if selected else _NODE_OUTLINE,
                width=2.5 if selected else 1.2,
            )
            center_x = (box[0] + box[2]) / 2
            center_y = (box[1] + box[3]) / 2
            text = self.canvas.create_text(
                center_x,
                center_y,
                text=positioned.node.label,
                fill="#ffffff" if selected else _MUTED if muted else _TEXT,
                font=("TkDefaultFont", font_size, "bold" if selected else "normal"),
            )
            self._node_items[rectangle] = node_id
            self._node_items[text] = node_id
        self._update_status()

    def _current_node_id(self) -> str | None:
        current = self.canvas.find_withtag("current")
        return self._node_items.get(current[0]) if current else None

    def _pointer_down(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.focus_set()
        node_id = self._current_node_id()
        if node_id is not None and event.num == 1:
            self.select_node(node_id)
            if self._on_select is not None:
                self._on_select(self._nodes[node_id].node)
            self._pan_anchor = None
            return
        if event.num == 1:
            self.clear_selection()
        self._pan_anchor = (event.x, event.y)
        self.canvas.configure(cursor="fleur")

    def _pointer_drag(self, event: tk.Event[tk.Misc]) -> None:
        if self._pan_anchor is None:
            return
        anchor_x, anchor_y = self._pan_anchor
        self._offset_x += event.x - anchor_x
        self._offset_y += event.y - anchor_y
        self._pan_anchor = (event.x, event.y)
        self._draw()

    def _pointer_activate(self, _event: tk.Event[tk.Misc]) -> None:
        node_id = self._current_node_id()
        if node_id is not None:
            self.activate_node(node_id)

    def _pointer_up(self, _event: tk.Event[tk.Misc]) -> None:
        self._pan_anchor = None
        self.canvas.configure(cursor="")

    def _mouse_wheel(self, event: tk.Event[tk.Misc]) -> None:
        self._wheel_step(event, 1 if event.delta > 0 else -1)

    def _wheel_step(self, event: tk.Event[tk.Misc], direction: int) -> None:
        self._zoom_at(1.15 if direction > 0 else 1 / 1.15, event.x, event.y)

    def _zoom_at(
        self,
        factor: float,
        screen_x: float | None = None,
        screen_y: float | None = None,
    ) -> None:
        if self._layout is None:
            return
        if screen_x is None:
            screen_x = max(self.canvas.winfo_width(), 200) / 2
        if screen_y is None:
            screen_y = max(self.canvas.winfo_height(), 160) / 2
        old_scale = self._scale
        new_scale = max(0.2, min(3.0, old_scale * factor))
        world_x = (screen_x - self._offset_x) / old_scale
        world_y = (screen_y - self._offset_y) / old_scale
        self._scale = new_scale
        self._offset_x = screen_x - world_x * new_scale
        self._offset_y = screen_y - world_y * new_scale
        self._draw()

    def _center_node(self, node_id: str) -> None:
        node = self._nodes[node_id]
        canvas_width = max(self.canvas.winfo_width(), 200)
        canvas_height = max(self.canvas.winfo_height(), 160)
        self._offset_x = canvas_width / 2 - (node.x + node.width / 2) * self._scale
        self._offset_y = canvas_height / 2 - (node.y + node.height / 2) * self._scale
