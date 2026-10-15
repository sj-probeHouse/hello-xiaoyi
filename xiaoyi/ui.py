"""Compact Chinese settings and reading card, built with Qt Widgets."""

from dataclasses import replace

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import PRESETS, Settings, get_key

STYLE = """
QWidget { font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 10pt; color: #203936; }
QWidget#settings, QWidget#card { background: #f5f8f5; }
QFrame#header { background: #e6eee8; border-radius: 12px; }
QLabel#brand { font-size: 21pt; font-weight: 700; color: #196556; }
QLabel#caption { color: #617770; font-size: 9pt; }
QLineEdit, QComboBox, QTextEdit {
    background: white; border: 1px solid #cddbd3; border-radius: 7px; padding: 7px;
    selection-background-color: #bbdfd0;
}
QTextEdit { padding: 10px; }
QPushButton {
    background: #e8efea; border: 1px solid #c9d9ce; border-radius: 7px; padding: 8px 13px;
}
QPushButton:hover { background: #d5e6dc; }
QPushButton:pressed, QPushButton:checked { background: #bcdace; }
QPushButton#primary { background: #206957; color: white; border: none; }
QPushButton#primary:hover { background: #185644; }
QPushButton:disabled { color: #8b9892; background: #edf0ed; }
QLabel#status { color: #526e63; padding: 5px 0; }
QCheckBox { spacing: 8px; }
QSlider::groove:horizontal { height: 5px; background: #d4e1d8; border-radius: 2px; }
QSlider::handle:horizontal { width: 15px; margin: -5px 0; background: #206957; border-radius: 7px; }
"""


def app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#206957"))
    painter.drawRoundedRect(3, 3, 58, 58, 16, 16)
    # Geometric open-book icon also renders on CI's fontless offscreen platform.
    painter.setBrush(QColor("#f4f6df"))
    painter.drawRoundedRect(13, 16, 38, 32, 5, 5)
    painter.setPen(QPen(QColor("#206957"), 3))
    painter.drawLine(32, 18, 32, 45)
    for y in (25, 32, 39):
        painter.drawLine(19, y, 26, y)
        painter.drawLine(38, y, 45, y)
    painter.end()
    return QIcon(pixmap)


class TranslationCard(QWidget):
    speak_requested = Signal()
    stop_requested = Signal()
    retry_requested = Signal()
    settings_requested = Signal()
    dismissed = Signal()
    auto_hidden = Signal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("card")
        self.setWindowTitle("你好，小译 · 阅读卡片")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowIcon(app_icon())
        self.resize(450, 480)
        self.setMinimumSize(360, 340)
        self.text = ""
        self.result = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        top = QHBoxLayout()
        brand = QLabel("HELLO XIAOYI")
        brand.setStyleSheet("font-weight: 700; color: #206957; letter-spacing: 2px;")
        top.addWidget(brand)
        top.addStretch()
        self.pin = QPushButton("固定")
        self.pin.setCheckable(True)
        self.pin.setToolTip("固定后，切换软件仍保留卡片")
        top.addWidget(self.pin)
        settings = QPushButton("设置")
        settings.clicked.connect(self.settings_requested)
        top.addWidget(settings)
        layout.addLayout(top)
        caption = QLabel("原文  /  ENGLISH")
        caption.setObjectName("caption")
        layout.addWidget(caption)
        self.original = QTextEdit()
        self.original.setReadOnly(True)
        self.original.setMaximumHeight(115)
        self.original.setAccessibleName("选中的英文原文")
        layout.addWidget(self.original)
        caption = QLabel("中文  /  TRANSLATION")
        caption.setObjectName("caption")
        layout.addWidget(caption)
        self.translation = QTextEdit()
        self.translation.setReadOnly(True)
        self.translation.setAccessibleName("中文翻译结果")
        layout.addWidget(self.translation, 1)
        self.status = QLabel("等待取词")
        self.status.setWordWrap(True)
        self.status.setObjectName("status")
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.speak = QPushButton("▶ 朗读原文")
        self.speak.setObjectName("primary")
        self.speak.clicked.connect(self.speak_requested)
        stop = QPushButton("停止")
        stop.clicked.connect(self.stop_requested)
        self.copy = QPushButton("复制译文")
        self.copy.clicked.connect(lambda: QApplication.clipboard().setText(self.result))
        self.retry = QPushButton("重试")
        self.retry.clicked.connect(self.retry_requested)
        for button in (self.speak, stop, self.copy, self.retry):
            actions.addWidget(button)
        layout.addLayout(actions)
        QShortcut(QKeySequence("Escape"), self, activated=self.close)

    def present(self, text: str, point: QPoint) -> None:
        self.text = text
        self.result = ""
        self.original.setPlainText(text)
        self.translation.clear()
        self.status.setText("正在翻译…")
        self.copy.setEnabled(False)
        self.retry.setVisible(False)
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.resize(min(self.width(), area.width()), min(self.height(), area.height()))
        x = min(max(area.left(), point.x() + 18), area.right() - self.width() + 1)
        y = min(max(area.top(), point.y() + 18), area.bottom() - self.height() + 1)
        if not self.pin.isChecked() or not self.isVisible():
            self.move(x, y)
        self.show()

    def append(self, value: str) -> None:
        self.result += value
        self.translation.setPlainText(self.result)

    def finish(self, text: str) -> None:
        self.result = text
        self.translation.setPlainText(text)
        self.copy.setEnabled(True)

    def error(self, message: str) -> None:
        self.status.setText(message)
        self.retry.setVisible(True)
        self.copy.setEnabled(False)

    def closeEvent(self, event) -> None:
        self.hide()
        self.dismissed.emit()
        event.ignore()

    def hide_passively(self) -> None:
        self.hide()
        self.auto_hidden.emit()

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            if self.isVisible() and not self.pin.isChecked():
                self.hide_passively()
        super().changeEvent(event)


class SettingsWindow(QWidget):
    save_requested = Signal(object, str)
    test_requested = Signal(object, str)
    preview_requested = Signal(object)
    stop_requested = Signal()
    clear_cache_requested = Signal()

    def __init__(self, settings: Settings, system_voices: list[tuple[str, str]]):
        super().__init__()
        self.setObjectName("settings")
        self.setWindowTitle("你好，小译 / HELLO XIAOYI · 设置")
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(620)
        self.current = replace(settings)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 20)
        header = QFrame()
        header.setObjectName("header")
        head = QVBoxLayout(header)
        head.setContentsMargins(18, 14, 18, 14)
        title = QLabel("你好，小译")
        title.setObjectName("brand")
        head.addWidget(title)
        subtitle = QLabel("HELLO XIAOYI  /  让阅读保持连贯")
        subtitle.setObjectName("caption")
        head.addWidget(subtitle)
        hint = QLabel("选中英文 → 按住 Ctrl 连按两次 C → 点击朗读")
        head.addWidget(hint)
        layout.addWidget(header)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.provider = QComboBox()
        self.provider.addItems(PRESETS)
        self.provider.setCurrentText(settings.provider)
        form.addRow("翻译服务", self.provider)
        self.base = QLineEdit(settings.base_url)
        self.base.setPlaceholderText("https://…（填写基础地址，不含 /chat/completions）")
        form.addRow("Base URL", self.base)
        self.model = QLineEdit(settings.model)
        form.addRow("模型名称", self.model)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("保存在 Windows 凭据管理器；清空后保存可删除")
        form.addRow("API Key", self.key)
        self.domain = QLineEdit(settings.domain)
        form.addRow("术语领域", self.domain)
        self.backend = QComboBox()
        self.backend.addItem("在线自然语音 · 无需密钥", "online")
        self.backend.addItem("Windows 系统语音 · 离线", "system")
        self.backend.setCurrentIndex(0 if settings.speech_backend == "online" else 1)
        form.addRow("朗读方式", self.backend)
        self.voice = QComboBox()
        voices = [
            ("美式 · Jenny（女）", "en-US-JennyNeural"),
            ("美式 · Aria（女）", "en-US-AriaNeural"),
            ("美式 · Guy（男）", "en-US-GuyNeural"),
            ("英式 · Sonia（女）", "en-GB-SoniaNeural"),
            ("英式 · Ryan（男）", "en-GB-RyanNeural"),
        ]
        for name, identifier in voices:
            self.voice.addItem(name, identifier)
        index = self.voice.findData(settings.voice)
        self.voice.setCurrentIndex(max(0, index))
        form.addRow("在线音色", self.voice)
        self.system_voice = QComboBox()
        for identifier, name in system_voices:
            self.system_voice.addItem(name, identifier)
        if not system_voices:
            self.system_voice.addItem("未检测到英文声音，请在 Windows 语音设置安装", "")
        index = self.system_voice.findData(settings.system_voice)
        self.system_voice.setCurrentIndex(max(0, index))
        form.addRow("系统音色", self.system_voice)
        self.rate = QSlider(Qt.Orientation.Horizontal)
        self.rate.setRange(-50, 100)
        self.rate.setValue(settings.rate)
        self.rate_label = QLabel(f"{settings.rate:+d}%")
        self.rate.valueChanged.connect(lambda value: self.rate_label.setText(f"{value:+d}%"))
        row = QHBoxLayout()
        row.addWidget(self.rate, 1)
        row.addWidget(self.rate_label)
        form.addRow("语速调整", row)
        self.startup = QCheckBox("登录 Windows 后自动在托盘启动")
        self.startup.setChecked(settings.startup)
        form.addRow("开机启动", self.startup)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.test_button = QPushButton("测试翻译连接")
        self.test_button.clicked.connect(self._test)
        preview = QPushButton("试听语音")
        preview.clicked.connect(self._preview)
        stop = QPushButton("停止")
        stop.clicked.connect(self.stop_requested)
        for button in (self.test_button, preview, stop):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.status = QLabel("就绪。API Key 只存本机；首次连接测试会发送一个短词并产生少量用量。")
        self.status.setWordWrap(True)
        self.status.setObjectName("status")
        layout.addWidget(self.status)
        privacy = QLabel(
            "翻译仅发送所选文字；在线朗读仅发送要读的英文。生词本与论文管理见项目路线图。"
        )
        privacy.setWordWrap(True)
        privacy.setObjectName("caption")
        layout.addWidget(privacy)
        bottom = QHBoxLayout()
        clear = QPushButton("清理音频缓存")
        clear.clicked.connect(self.clear_cache_requested)
        bottom.addWidget(clear)
        bottom.addStretch()
        save = QPushButton("保存设置")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        bottom.addWidget(save)
        layout.addLayout(bottom)
        self.provider.currentTextChanged.connect(self._provider_changed)
        self.base.editingFinished.connect(self._load_key)
        self.backend.currentIndexChanged.connect(self._backend_changed)
        self._backend_changed()
        self._load_key()

    def _backend_changed(self) -> None:
        online = self.backend.currentData() == "online"
        self.voice.setEnabled(online)
        self.system_voice.setEnabled(not online)

    def _provider_changed(self, provider: str) -> None:
        base, model = PRESETS[provider]
        self.base.setText(base)
        self.model.setText(model)
        self._load_key()

    def _load_key(self) -> None:
        try:
            self.key.setText(get_key(self.base.text().strip()))
        except RuntimeError as exc:
            self.key.clear()
            self.status.setText(str(exc))

    def snapshot(self) -> Settings:
        settings = Settings(
            provider=self.provider.currentText(),
            base_url=self.base.text().strip().rstrip("/"),
            model=self.model.text().strip(),
            domain=self.domain.text().strip(),
            voice=self.voice.currentData(),
            rate=self.rate.value(),
            speech_backend=self.backend.currentData(),
            system_voice=self.system_voice.currentData(),
            startup=self.startup.isChecked(),
        )
        settings.validate()
        return settings

    def _save(self) -> None:
        try:
            self.save_requested.emit(self.snapshot(), self.key.text().strip())
        except ValueError as exc:
            self.status.setText(str(exc))

    def _test(self) -> None:
        try:
            self.test_requested.emit(self.snapshot(), self.key.text().strip())
        except ValueError as exc:
            self.status.setText(str(exc))

    def _preview(self) -> None:
        # Voice preview works before a translation key/base URL has been configured.
        self.preview_requested.emit(
            replace(
                self.current,
                voice=self.voice.currentData(),
                rate=self.rate.value(),
                speech_backend=self.backend.currentData(),
                system_voice=self.system_voice.currentData(),
            )
        )

    def closeEvent(self, event) -> None:
        self.hide()
        event.ignore()
