import logging
import os
import base64
import json
import shutil
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget,
    QTreeWidgetItem, QTextEdit, QLabel, QPushButton, QFileDialog, QGroupBox,
    QLineEdit, QComboBox, QHeaderView, QMessageBox
)
from PyQt5.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap, QColor


class EvidenceWidget(QWidget):
    reports_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.reports = {}
        self.current_report = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header_group = QGroupBox("Подозрительные действия")
        header_layout = QHBoxLayout(header_group)
        self.summary_label = QLabel("Ни одного подтверждения не получено")
        header_layout.addWidget(self.summary_label)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск по подозрительным действиям...")
        self.search_input.textChanged.connect(self.apply_filter)
        self.search_input.setMinimumWidth(260)
        header_layout.addWidget(self.search_input)

        header_layout.addStretch()
        self.save_btn = QPushButton("Сохранить выбранный отчет")
        self.save_btn.clicked.connect(self.save_selected_report)
        self.save_btn.setEnabled(False)
        header_layout.addWidget(self.save_btn)

        self.delete_btn = QPushButton("Удалить выбранные")
        self.delete_btn.clicked.connect(self.delete_selected_reports)
        self.delete_btn.setEnabled(False)
        header_layout.addWidget(self.delete_btn)

        self.table = QTreeWidget()
        self.table.setColumnCount(4)
        self.table.setHeaderLabels(["Время", "Процесс", "Описание", "Статус"])
        self.table.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setRootIsDecorated(True)
        self.table.setAllColumnsShowFocus(True)
        self.table.setSelectionMode(self.table.ExtendedSelection)
        self.table.setEditTriggers(self.table.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)

        details_group = QGroupBox("Детали подозрительного действия")
        details_layout = QVBoxLayout(details_group)
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)

        preview_layout = QHBoxLayout()
        preview_layout.addWidget(QLabel("Просмотр:"))
        self.preview_combo = QComboBox()
        self.preview_combo.addItems(["Скриншот", "Камера"])
        self.preview_combo.setEnabled(False)
        self.preview_combo.currentIndexChanged.connect(lambda _: self._update_image())
        preview_layout.addWidget(self.preview_combo)
        preview_layout.addStretch()

        details_layout.addLayout(preview_layout)
        details_layout.addWidget(self.details_text)
        self.image_label = QLabel("Выберите запись для просмотра")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(400, 250)
        self.image_label.setStyleSheet("background-color: #2b2b2b; border: 1px solid #555;")
        details_layout.addWidget(self.image_label)

        splitter = QSplitter(Qt.Vertical)
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.addWidget(self.table)
        splitter.addWidget(top_widget)
        splitter.addWidget(details_group)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(header_group)
        layout.addWidget(splitter)

    def add_report(self, report):
        event_id = report.get('event_id')
        if not event_id:
            return

        self.reports[event_id] = report
        self.apply_filter()
        self.reports_changed.emit()

    def apply_filter(self):
        search_text = self.search_input.text().strip().lower()
        selected_event = self._get_selected_event_id()
        scroll_value = self.table.verticalScrollBar().value()

        self.table.setUpdatesEnabled(False)
        self.table.clear()
        self.table.setHeaderLabels(["Время", "Процесс", "Описание", "Статус"])

        grouped = {}
        for report in self.reports.values():
            if search_text and not self._matches_search(report, search_text):
                continue

            client_name = report.get('client_hostname', report.get('client_id', 'unknown'))
            if client_name not in grouped:
                group_item = QTreeWidgetItem(self.table)
                group_item.setText(0, f"{client_name}")
                group_item.setFirstColumnSpanned(True)
                group_item.setData(0, Qt.UserRole, None)
                group_item.setExpanded(True)
                grouped[client_name] = group_item

            self._add_report_to_group(grouped[client_name], report)

        for client_name, group_item in grouped.items():
            count = group_item.childCount()
            group_item.setText(0, f"{client_name} ({count})")

        self._restore_selected_event(selected_event)
        self._update_summary()
        self.table.setUpdatesEnabled(True)
        QTimer.singleShot(0, lambda: self.table.verticalScrollBar().setValue(scroll_value))

    def _get_selected_event_id(self):
        selected_items = self.table.selectedItems()
        if not selected_items:
            return None
        return selected_items[0].data(0, Qt.UserRole)

    def _get_selected_event_ids(self):
        selected_items = self.table.selectedItems()
        event_ids = []
        for item in selected_items:
            event_id = item.data(0, Qt.UserRole)
            if event_id:
                event_ids.append(event_id)
        return list(dict.fromkeys(event_ids))

    def _restore_selected_event(self, event_id):
        if not event_id:
            return
        root_count = self.table.topLevelItemCount()
        for i in range(root_count):
            group_item = self.table.topLevelItem(i)
            for j in range(group_item.childCount()):
                report_item = group_item.child(j)
                if report_item.data(0, Qt.UserRole) == event_id:
                    self.table.setCurrentItem(report_item)
                    return

    def _add_report_to_group(self, group_item, report):
        report_item = QTreeWidgetItem(group_item)
        event_time = report.get('received_at', report.get('timestamp', ''))
        process = report.get('process', {}).get('command', '')
        description = report.get('description', '')
        status = report.get('status', 'delivered')

        report_item.setText(0, event_time)
        report_item.setText(1, process)
        report_item.setText(2, description)
        report_item.setText(3, status)
        report_item.setData(0, Qt.UserRole, report.get('event_id'))

    def _matches_search(self, report, search_text):
        fields = [
            report.get('event_id', ''),
            report.get('client_hostname', report.get('client_id', '')),
            report.get('description', ''),
            report.get('status', ''),
            report.get('process', {}).get('command', ''),
            report.get('process', {}).get('args', ''),
            report.get('process', {}).get('matched_keyword', '')
        ]
        return any(search_text in str(field).lower() for field in fields)

    def _update_summary(self):
        total = len(self.reports)
        visible = 0
        for i in range(self.table.topLevelItemCount()):
            visible += self.table.topLevelItem(i).childCount()

        if total == 0:
            self.summary_label.setText("Ни одного подтверждения не получено")
        elif visible == 0:
            self.summary_label.setText(f"Ни одного соответствия не найдено ({total} всего)")
        elif visible == total:
            self.summary_label.setText(f"Получено подтверждений: {total}")
        else:
            self.summary_label.setText(f"Показано {visible} из {total} заявок")

    def on_selection_changed(self):
        selected_ids = self._get_selected_event_ids()
        if not selected_ids:
            self.current_report = None
            self.details_text.setPlainText("")
            self.image_label.setText("Выберите запись для просмотра")
            self.save_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            self.preview_combo.setEnabled(False)
            return

        self.delete_btn.setEnabled(True)
        if len(selected_ids) == 1:
            report = self.reports.get(selected_ids[0])
            self.current_report = report
            self.save_btn.setEnabled(True)
            self.details_text.setPlainText(self._format_report_details(report))
            self.preview_combo.setEnabled(bool(report.get('camera_path')))
            if not report.get('camera_path'):
                self.preview_combo.setCurrentIndex(0)
            self._update_image()
        else:
            self.current_report = None
            self.save_btn.setEnabled(False)
            self.preview_combo.setEnabled(False)
            self.details_text.setPlainText(f"Выбрано отчетов: {len(selected_ids)}")
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("Выбрано несколько отчетов")

    def _format_report_details(self, report):
        process = report.get('process', {})
        lines = [
            f"ID: {report.get('event_id', '')}",
            f"Клиент: {report.get('client_hostname', report.get('client_id', 'unknown'))}",
            f"Время события: {report.get('timestamp', '')}",
            f"Время получения: {report.get('received_at', '')}",
            f"Статус: {report.get('status', '')}",
            "",
            f"Процесс: {process.get('command', '')}",
            f"Аргументы: {process.get('args', '')}",
            f"Совпавший ключ: {process.get('matched_keyword', '')}",
            "",
            f"Описание: {report.get('description', '')}",
        ]
        if report.get('screenshot_path'):
            lines.append(f"Скриншот: {report.get('screenshot_path')}")
        if report.get('camera_path'):
            lines.append(f"Камера: {report.get('camera_path')}")
        return "\n".join(lines)

    def _update_image(self, report=None):
        if report is None:
            report = self.current_report
        if not report:
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("Выберите запись для просмотра")
            return

        image_path = self._get_preview_image_path(report)
        if image_path and os.path.exists(image_path):
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.image_label.setPixmap(scaled)
                return
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText("Изображение недоступно")

    def _get_preview_image_path(self, report):
        if self.preview_combo.currentText() == "Камера":
            return report.get('camera_path') or report.get('screenshot_path')
        return report.get('screenshot_path') or report.get('camera_path')

    def save_selected_report(self):
        selected_ids = self._get_selected_event_ids()
        if len(selected_ids) != 1:
            return
        report = self.reports.get(selected_ids[0])
        if not report:
            return

        directory = QFileDialog.getExistingDirectory(self, "Сохранить доказательство в папку")
        if not directory:
            return

        try:
            source_dir = report.get('storage_path')
            if source_dir and os.path.isdir(source_dir):
                dest_dir = os.path.join(directory, report.get('event_id'))
                shutil.copytree(source_dir, dest_dir, dirs_exist_ok=True)
                self.details_text.append(f"\nДоказательство сохранено: {dest_dir}")
            else:
                self.details_text.append("\nНе удалось найти файлы доказательства для сохранения.")
        except Exception as e:
            self.details_text.append(f"\nОшибка сохранения: {e}")

    def delete_selected_reports(self):
        selected_ids = self._get_selected_event_ids()
        if not selected_ids:
            return

        count = len(selected_ids)
        reply = QMessageBox.question(
            self,
            "Удалить отчеты",
            f"Удалить {count} выбранный(е) отчет(а)?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        for event_id in selected_ids:
            report = self.reports.pop(event_id, None)
            if report and report.get('storage_path') and os.path.isdir(report['storage_path']):
                try:
                    shutil.rmtree(report['storage_path'], ignore_errors=True)
                except Exception as e:
                    logging.warning(f"Не удалось удалить папку отчета {event_id}: {e}")
        self.apply_filter()
        self.reports_changed.emit()
        self.current_report = None
        self.save_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.preview_combo.setEnabled(False)
        self.details_text.setPlainText("")
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText("Выберите запись для просмотра")
