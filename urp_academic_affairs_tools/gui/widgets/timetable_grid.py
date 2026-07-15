from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from urp_academic_affairs_tools.parser.timetable import TimetableEntry

TIMETABLE_SESSION_COUNT = 12
WEEKDAY_COUNT = 7
LUNCH_BREAK_AFTER_SESSION = 4
LUNCH_BREAK_ROW = LUNCH_BREAK_AFTER_SESSION
TIMETABLE_TABLE_ROW_COUNT = TIMETABLE_SESSION_COUNT + 1
TIMETABLE_SESSION_TIMES = (
    ("08:30", "09:15"),
    ("09:20", "10:05"),
    ("10:20", "11:05"),
    ("11:10", "11:55"),
    ("13:30", "14:15"),
    ("14:20", "15:05"),
    ("15:20", "16:05"),
    ("16:10", "16:55"),
    ("17:10", "17:55"),
    ("18:00", "18:45"),
    ("19:00", "19:45"),
    ("19:50", "20:35"),
)


class TimetableGrid(QTableWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(TIMETABLE_TABLE_ROW_COUNT, WEEKDAY_COUNT + 1, parent)
        self.course_colors: dict[str, tuple[str, str, str]] = {}
        self.setObjectName("TimetableTable")
        self.setHorizontalHeaderLabels(
            ["节次 / 时间", "周一", "周二", "周三", "周四", "周五", "周六", "周日"],
        )
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(76)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 98)
        for column in range(1, WEEKDAY_COUNT + 1):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self._reset()

    def render_entries(self, entries: Sequence[TimetableEntry]) -> int:
        self._reset()
        slots: dict[tuple[int, int, int], list[TimetableEntry]] = {}
        invalid_count = 0
        for entry in entries:
            slot = self._slot(entry)
            if slot is None:
                invalid_count += 1
                continue
            slots.setdefault(slot, []).append(entry)

        occupied_count: dict[tuple[int, int], int] = {}
        for day, start, duration in slots:
            for session in range(start, start + duration):
                cell = (self._table_row(session), day)
                occupied_count[cell] = occupied_count.get(cell, 0) + 1

        fallback_cells: dict[tuple[int, int], list[TimetableEntry]] = {}
        for (day, start, duration), slot_entries in sorted(slots.items()):
            rows = [
                self._table_row(session) for session in range(start, start + duration)
            ]
            cells = [(row, day) for row in rows]
            is_continuous = rows == list(range(rows[0], rows[0] + duration))
            if not is_continuous or any(occupied_count[cell] > 1 for cell in cells):
                for cell in cells:
                    fallback_cells.setdefault(cell, []).extend(slot_entries)
                continue
            self.setSpan(rows[0], day, duration, 1)
            self.setCellWidget(rows[0], day, self._course_widget(slot_entries))

        for (row, day), cell_entries in fallback_cells.items():
            self.setCellWidget(row, day, self._course_widget(cell_entries))
        return invalid_count

    def _reset(self) -> None:
        self.clearSpans()
        self.clearContents()
        for session, (start_time, end_time) in enumerate(
            TIMETABLE_SESSION_TIMES,
            start=1,
        ):
            item = QTableWidgetItem(f"第{session}节\n{start_time}–{end_time}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            row = self._table_row(session)
            self.setItem(row, 0, item)
            self.setRowHeight(row, 76)

        lunch_item = QTableWidgetItem("午休")
        lunch_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        lunch_item.setForeground(QColor("#7b9a8d"))
        lunch_item.setToolTip("午休时段：11:55–13:30")
        self.setItem(LUNCH_BREAK_ROW, 0, lunch_item)
        self.setRowHeight(LUNCH_BREAK_ROW, 22)
        self.setSpan(LUNCH_BREAK_ROW, 1, 1, WEEKDAY_COUNT)
        lunch_label = QLabel("午休 · 11:55–13:30")
        lunch_label.setObjectName("TimetableLunchBreak")
        lunch_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lunch_label.setToolTip("午休时段：11:55–13:30")
        self.setCellWidget(LUNCH_BREAK_ROW, 1, lunch_label)

    @staticmethod
    def _slot(entry: TimetableEntry) -> tuple[int, int, int] | None:
        day = entry["day"]
        start = entry["start_session"]
        if day is None or start is None or not 1 <= day <= WEEKDAY_COUNT or start < 1:
            return None
        duration = min(
            entry["duration"] or 1,
            TIMETABLE_SESSION_COUNT - start + 1,
        )
        return (day, start, duration) if duration > 0 else None

    @staticmethod
    def _table_row(session: int) -> int:
        return session - 1 + int(session > LUNCH_BREAK_AFTER_SESSION)

    def _course_widget(self, entries: Sequence[TimetableEntry]) -> QWidget:
        grouped: dict[str, list[TimetableEntry]] = {}
        for entry in entries:
            grouped.setdefault(self._course_key(entry), []).append(entry)
        if len(grouped) == 1:
            return self._course_label(next(iter(grouped.values())))

        group = QWidget()
        layout = QVBoxLayout(group)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(3)
        for course_entries in grouped.values():
            layout.addWidget(self._course_label(course_entries))
        return group

    @staticmethod
    def _course_key(entry: TimetableEntry) -> str:
        return "\x1f".join((entry["course_name"], entry["course_sequence_number"]))

    def _colors(self, entry: TimetableEntry) -> tuple[str, str, str]:
        course_key = self._course_key(entry)
        colors = self.course_colors.get(course_key)
        if colors is None:
            hue = int((len(self.course_colors) * 137.508 + 148) % 360)
            colors = (
                QColor.fromHsl(hue, 118, 226).name(),
                QColor.fromHsl(hue, 105, 160).name(),
                QColor.fromHsl(hue, 72, 56).name(),
            )
            self.course_colors[course_key] = colors
        return colors

    def _course_label(self, entries: Sequence[TimetableEntry]) -> QLabel:
        fill_color, border_color, text_color = self._colors(entries[0])
        compact = len(entries) == 1 and (entries[0]["duration"] or 1) == 1
        full_text = "\n\n".join(self._entry_text(entry) for entry in entries)
        text = self._compact_entry_text(entries[0]) if compact else full_text
        label = QLabel(text)
        label.setObjectName("TimetableCourse")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        if compact:
            label.setContentsMargins(4, 2, 4, 2)
        else:
            label.setContentsMargins(6, 5, 6, 5)
        label.setToolTip(full_text)
        font_size = "font-size: 11px;" if compact else ""
        label.setStyleSheet(
            "QLabel {"
            f"background: {fill_color}; border: 1px solid {border_color}; "
            f"border-radius: 7px; color: {text_color};{font_size}"
            "}",
        )
        return label

    @staticmethod
    def _compact_entry_text(entry: TimetableEntry) -> str:
        sequence = entry["course_sequence_number"]
        course = entry["course_name"]
        course_label = f"{course}_{sequence}" if sequence else course
        start = entry["start_session"]
        session_label = f"第{start}节" if start is not None else ""
        weeks = entry["week_desc"] or str(entry["weeks"])
        details = [
            course_label,
            " · ".join(part for part in (entry["teacher"], session_label) if part),
            " · ".join(part for part in (weeks, entry["building"]) if part),
        ]
        return "\n".join(detail for detail in details if detail)

    @staticmethod
    def _entry_text(entry: TimetableEntry) -> str:
        sequence = entry["course_sequence_number"]
        course = entry["course_name"]
        course_label = f"{course}_{sequence}" if sequence else course
        start = entry["start_session"]
        duration = entry["duration"] or 1
        end = start + duration - 1 if start is not None else None
        session_label = f"第{start}-{end}节" if end != start else f"第{start}节"
        location = " ".join(
            part for part in (entry["building"], entry["classroom"]) if part
        )
        weeks = entry["week_desc"] or str(entry["weeks"])
        details = [course_label, entry["teacher"], weeks, session_label, location]
        return "\n".join(detail for detail in details if detail)
