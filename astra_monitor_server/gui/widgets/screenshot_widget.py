# astra_monitor_server/gui/widgets/screenshot_widget.py

import base64
import asyncio
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                             QPushButton, QLabel, QScrollArea, QFileDialog)
from PyQt5.QtCore import Qt, QTimer, QDateTime
from PyQt5.QtGui import QImage, QPixmap

class ScreenshotWidget(QWidget):
    def __init__(self, parent=None, ws_server=None, client_id=None, log_callback=None, settings_screenshot={}):
        super().__init__(parent)
        self.ws_server = ws_server
        self.client_id = client_id
        self.log_callback = log_callback or (lambda msg: print(msg))
        self.current_image = None
        self.settings_screenshot = settings_screenshot.get('screenshot',{})
        self.auto_refresh_timer = QTimer()
        self.auto_refresh_timer.timeout.connect(self.take_screenshot)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Панель управления
        control_group = QGroupBox("🖥️ Управление экраном")
        control_layout = QHBoxLayout(control_group)
                
        # Кнопки управления
        self.take_btn = QPushButton("📸 Сделать снимок")
        self.take_btn.clicked.connect(self.take_screenshot)
        control_layout.addWidget(self.take_btn)
        
        self.auto_refresh_btn = QPushButton("🔄 Автообновление")
        self.auto_refresh_btn.setCheckable(True)
        self.auto_refresh_btn.clicked.connect(self.toggle_auto_refresh)
        control_layout.addWidget(self.auto_refresh_btn)
        
        control_layout.addStretch()
        
        # Область отображения скриншота
        image_group = QGroupBox("🖼️ Экран клиента")
        image_layout = QVBoxLayout(image_group)
        
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(400, 300)
        self.image_label.setStyleSheet("background-color: #2b2b2b; border: 1px solid #555;")
        self.image_label.setText("Нажмите '📸 Сделать снимок' для получения изображения")
        
        # Scroll area для больших экранов
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.image_label)
        
        image_layout.addWidget(scroll_area)
        
        # Информация о снимке
        info_layout = QHBoxLayout()
        self.info_label = QLabel("Размер: - | Время: -")
        self.save_btn = QPushButton("💾 Сохранить")
        self.save_btn.clicked.connect(self.save_screenshot)
        self.save_btn.setEnabled(False)
        
        info_layout.addWidget(self.info_label)
        info_layout.addStretch()
        info_layout.addWidget(self.save_btn)
        
        image_layout.addLayout(info_layout)
        
        layout.addWidget(control_group)
        layout.addWidget(image_group)
        
    def take_screenshot(self):
        """Запрос скриншота с определенным качеством"""
        quality = self.settings_screenshot.get('quality', 85)
        self.log_callback(f"📸 Запрос скриншота (качество: {quality}%)")
        
        future = asyncio.run_coroutine_threadsafe(
            self.ws_server.send_command(self.client_id, f"screenshot_quality:{quality}"), 
            self.ws_server.loop
        )
    
    def toggle_auto_refresh(self, checked):
        """Включение/выключение автоматического обновления"""
        if checked:
            delay = self.settings_screenshot.get('refresh_delay', 5) * 1000  # convert to milliseconds
            self.auto_refresh_timer.start(delay)
            self.log_callback(f"🔄 Автообновление включено (каждые {self.settings_screenshot.get('refresh_delay', 5)} сек)")
        else:
            self.auto_refresh_timer.stop()
            self.log_callback("🔄 Автообновление выключено")
    
    def update_screenshot(self, image_data, quality, timestamp):
        """Обновление отображаемого скриншота"""
        try:
            # Декодируем base64
            img_data = base64.b64decode(image_data)
            
            # Создаем QImage из данных
            image = QImage()
            image.loadFromData(img_data)
            
            if image.isNull():
                self.log_callback("❌ Не удалось загрузить изображение")
                return
            
            # Масштабируем для отображения (сохраняем пропорции)
            pixmap = QPixmap.fromImage(image)
            scaled_pixmap = pixmap.scaled(
                self.image_label.width() - 20, 
                self.image_label.height() - 20,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            self.image_label.setPixmap(scaled_pixmap)
            self.current_image = pixmap  # Сохраняем оригинальное изображение
            
            # Обновляем информацию
            size_text = f"{pixmap.width()}x{pixmap.height()}"
            time_text = QDateTime.fromString(timestamp, Qt.ISODate).toString("dd.MM.yyyy HH:mm:ss")
            self.info_label.setText(f"Размер: {size_text} | Качество: {quality}% | Время: {time_text}")
            
            self.save_btn.setEnabled(True)
            self.log_callback(f"✅ Скриншот получен ({size_text}, качество: {quality}%)")
            
        except Exception as e:
            self.log_callback(f"❌ Ошибка обработки скриншота: {str(e)}")
    
    def save_screenshot(self):
        """Сохранение скриншота в файл"""
        if not self.current_image:
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "💾 Сохранить скриншот", 
            f"screenshot_{QDateTime.currentDateTime().toString('yyyyMMdd_hhmmss')}.png",
            "Images (*.png *.jpg *.jpeg)"
        )
        
        if file_path:
            try:
                self.current_image.save(file_path)
                self.log_callback(f"✅ Скриншот сохранен: {file_path}")
            except Exception as e:
                self.log_callback(f"❌ Ошибка сохранения: {str(e)}")