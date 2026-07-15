from __future__ import annotations


def load_stylesheet() -> str:
    return """
    QWidget { font-family: 'Segoe UI', 'Microsoft YaHei'; font-size: 13px; color: #30403c; }
    QMainWindow, QWidget { background: #eaf3ef; }
    QWidget#Sidebar { background: rgba(225, 240, 233, 225); border: 1px solid rgba(255, 255, 255, 180); border-radius: 16px; }
    QFrame#AccountCard { background: rgba(255, 255, 255, 185); border: 1px solid rgba(255, 255, 255, 220); border-radius: 13px; }
    QFrame#ClockCard { background: rgba(255, 255, 255, 125); border: 1px solid rgba(255, 255, 255, 175); border-radius: 11px; }
    QLabel#AccountCaption { color: #7f938b; font-size: 11px; font-weight: 600; }
    QLabel#AccountName { color: #28443b; font-size: 16px; font-weight: 700; }
    QLabel#AccountStatus { color: #4d9278; background: rgba(221, 241, 231, 150); border-radius: 7px; font-size: 12px; padding: 4px 6px; }
    QLabel#LoginTime, QLabel#CurrentTime { color: #56766b; font-size: 12px; font-weight: 600; }
    QPushButton#LogoutButton { background: rgba(244, 250, 247, 160); border: 1px solid rgba(133, 165, 150, 110); color: #557269; padding: 7px 10px; }
    QPushButton#LogoutButton:hover { background: rgba(255, 255, 255, 230); border-color: #8aa99b; }
    QListWidget#Navigation { background: transparent; color: #587168; border: 0; padding: 2px; }
    QListWidget#Navigation::item { padding: 12px 11px; border-radius: 10px; margin: 2px 0; }
    QListWidget#Navigation::item:hover { background: rgba(255, 255, 255, 120); }
    QListWidget#Navigation::item:selected { background: rgba(255, 255, 255, 205); color: #286b56; font-weight: 700; }
    QPushButton { background: #4d9a80; color: white; border: 1px solid rgba(255, 255, 255, 100); border-radius: 9px; padding: 9px 14px; font-weight: 600; }
    QPushButton:hover { background: #3d876e; }
    QPushButton#SwitchAccountButton { background: rgba(244, 250, 247, 180); color: #517368; border: 1px solid rgba(133, 165, 150, 120); padding: 7px 10px; }
    QPushButton#SwitchAccountButton:hover { background: rgba(255, 255, 255, 230); }
    QToolButton#CourseMode { min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; background: transparent; border: 0; padding: 0 0 4px; color: #527368; font-size: 16px; font-weight: 700; }
    QToolButton#CourseMode:hover { background: rgba(255, 255, 255, 130); border-radius: 15px; color: #2f6f59; }
    QToolButton#CourseMode::menu-indicator { image: none; width: 0; }
    QPushButton#ScoreAction, QToolButton#PassingScores { min-width: 106px; max-width: 106px; min-height: 32px; max-height: 32px; background: #4d9a80; color: white; border: 1px solid rgba(255, 255, 255, 100); border-radius: 8px; padding: 0 8px; font-weight: 600; }
    QPushButton#ScoreAction:hover, QToolButton#PassingScores:hover { background: #3d876e; }
    QToolButton#PassingScores::menu-indicator { image: none; width: 0; }
    QMenu { background: #f6fbf8; border: 1px solid #a9c8ba; border-radius: 8px; padding: 5px; color: #41675a; }
    QMenu::item { padding: 8px 24px 8px 12px; border-radius: 5px; }
    QMenu::item:selected { background: #dcefe6; }
    QComboBox#ScoreTerm { background: rgba(255, 255, 255, 175); border: 1px solid rgba(155, 190, 174, 135); border-radius: 9px; padding: 8px 10px; color: #41675a; }
    QComboBox#ScoreTerm:hover { background: rgba(255, 255, 255, 225); border-color: #82ae9d; }
    QComboBox#ScoreTerm::drop-down { width: 24px; border: 0; border-left: 1px solid rgba(155, 190, 174, 110); }
    QComboBox#ScoreTerm QAbstractItemView { background: #f6fbf8; border: 1px solid #a9c8ba; border-radius: 8px; padding: 4px; selection-background-color: #dcefe6; selection-color: #365b4e; }
    QTableWidget { background: rgba(255, 255, 255, 185); border: 1px solid rgba(255, 255, 255, 215); border-radius: 12px; gridline-color: rgba(195, 215, 205, 100); }
    QTableWidget::item:hover { background: rgba(211, 232, 221, 135); color: #30403c; }
    QTableWidget::item:selected { background: rgba(202, 228, 214, 170); color: #30403c; }
    QScrollBar:vertical { background: transparent; border: 0; width: 10px; margin: 7px 2px; }
    QScrollBar::handle:vertical { background: rgba(87, 128, 112, 125); min-height: 36px; margin: 0 1px; border: 0; border-radius: 4px; }
    QScrollBar::handle:vertical:hover { background: rgba(66, 109, 93, 175); }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
    QScrollBar:horizontal { background: transparent; border: 0; height: 10px; margin: 2px 7px; }
    QScrollBar::handle:horizontal { background: rgba(87, 128, 112, 125); min-width: 36px; margin: 1px 0; border: 0; border-radius: 4px; }
    QScrollBar::handle:horizontal:hover { background: rgba(66, 109, 93, 175); }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
    QCheckBox#CourseTaskCheck::indicator { width: 14px; height: 14px; border: 1px solid #92aca1; border-radius: 4px; background: rgba(255, 255, 255, 190); }
    QCheckBox#CourseTaskCheck::indicator:checked { background: #4d9a80; border-color: #4d9a80; }
    QHeaderView::section { background: rgba(233, 244, 238, 185); padding: 9px; border: 0; font-weight: 600; color: #426258; }
    QLabel#PageTitle { font-size: 25px; font-weight: 700; color: #365b4e; }
    QLabel#PageSubtitle { color: #738a80; padding-bottom: 10px; }
    QLabel#HomeTitle { color: #365b4e; font-size: 30px; font-weight: 700; letter-spacing: 1px; }
    QLabel#HomeSubtitle { color: #769087; font-size: 15px; padding-top: 8px; }
    QLabel#CourseTerm { color: #477565; font-weight: 600; padding: 4px 0 8px; }
    QLabel#CumulativeAverageGpa, QLabel#SelectedTermAverageGpa { color: #2f6f59; font-size: 15px; font-weight: 700; padding: 3px 0 5px; }
    QLabel#ScoreNotice, QLabel#TimetableNotice { color: #5e8374; background: rgba(255, 255, 255, 135); border-radius: 8px; padding: 7px 10px; }
    QLabel#TimetableLunchBreak { color: #7b9a8d; background: transparent; font-size: 11px; font-weight: 600; }
    QLabel#InlineLoading { color: #4a806d; background: rgba(255, 255, 255, 170); border: 1px solid rgba(178, 205, 192, 150); border-radius: 10px; padding: 5px 10px; font-weight: 600; }
    QTableWidget#TimetableTable { background: rgba(255, 255, 255, 205); border: 1px solid rgba(155, 190, 174, 150); border-radius: 10px; gridline-color: rgba(181, 207, 195, 160); }
    QTableWidget#TimetableTable QHeaderView::section { background: rgba(220, 239, 230, 220); color: #3d6e5b; font-weight: 700; padding: 9px; border: 0; border-right: 1px solid rgba(181, 207, 195, 120); }
    QFrame#EvaluationCardPending, QFrame#EvaluationCardDone { background: rgba(255, 255, 255, 185); border-radius: 13px; border: 1px solid rgba(255, 255, 255, 220); }
    QFrame#EvaluationCardPending { border-left: 4px solid #5aaf90; }
    QFrame#EvaluationCardDone { border-left: 4px solid #93b8a8; }
    QLabel#StatusPending { color: #33775f; background: #e1f2ea; border-radius: 12px; padding: 5px 10px; font-weight: 700; }
    QLabel#StatusDone { color: #6d8d80; background: #edf4f0; border-radius: 12px; padding: 5px 10px; font-weight: 700; }
    QLabel#EvaluationCourse { font-size: 15px; font-weight: 700; color: #38594e; }
    QLabel#EvaluationMeta { color: #7b9187; padding-top: 3px; }
    QLabel#EmptyState { color: #71877e; font-size: 15px; padding: 38px; }
    """
