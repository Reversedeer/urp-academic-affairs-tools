from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTableWidget


def configure_table(table: QTableWidget, widths: list[int]) -> None:
    header = table.horizontalHeader()
    for index, width in enumerate(widths):
        mode = QHeaderView.ResizeMode.Fixed if width else QHeaderView.ResizeMode.Stretch
        header.setSectionResizeMode(index, mode)
        if mode is QHeaderView.ResizeMode.Fixed:
            header.resizeSection(index, width)
    header.setStretchLastSection(True)
    table.setWordWrap(True)
    table.setTextElideMode(Qt.TextElideMode.ElideNone)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(40)
