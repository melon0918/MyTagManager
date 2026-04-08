import sys
import os
import sqlite3
import shutil
import gc
from pathlib import Path
from PySide6.QtCore import (Qt, QSize, QPoint, QRect, QMimeData, 
                            Signal, QEvent, QTimer, QObject, 
                            QVariantAnimation, QEasingCurve)
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QListWidget, QListWidgetItem, 
                             QLabel, QFileDialog, QFrame, QScrollArea, QSplitter,
                             QInputDialog, QLayout, QLineEdit, QMenu, QMessageBox, 
                             QStackedWidget, QWidgetItem, QComboBox)
from PySide6.QtGui import QPixmap, QDrag, QCursor, QColor, QPainter, QAction
from PySide6.QtCore import Qt, QSize, QPoint, QRect, QMimeData, Signal, QEvent, QTimer
from library_engine import LibraryEngine

# --- 通用样式 ---
MENU_STYLE = """
    QMenu { background: white; border: 1px solid #ddd; padding: 5px; } 
    QMenu::item { padding: 6px 28px; color: #333; font-size: 13px; }
    QMenu::item:selected { background: #0078d4; color: white; }
"""

NAV_BTN_STYLE = """
    QPushButton { border: none; border-radius: 4px; padding: 8px; color: #666; font-weight: bold; }
    QPushButton:hover { background: #eee; }
    QPushButton[active="true"] { background: #e1f0ff; color: #0078d4; }
"""

# --- 1. 流式布局 ---
class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        if parent is not None: self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self.itemList = []

    def __del__(self):
        while self.itemList: self.takeAt(0)

    def addItem(self, item): self.itemList.append(item)
    
    # 核心修复：确保 widget 挂载、显示并触发重绘
    def insertWidget(self, index, widget):
        widget.setParent(self.parentWidget()) 
        widget.show() # 关键：确保新插入的 widget 是可见状态
        item = QWidgetItem(widget)
        self.itemList.insert(index, item)
        self.invalidate() # 触发重新计算布局

    def count(self): return len(self.itemList)
    def itemAt(self, index): return self.itemList[index] if 0 <= index < len(self.itemList) else None
    
    def takeAt(self, index): 
        if 0 <= index < len(self.itemList):
            item = self.itemList.pop(index)
            self.invalidate()
            return item
        return None

    def expandingDirections(self): return Qt.Orientations(0)
    def hasHeightForWidth(self): return True
    def heightForWidth(self, width): return self._doLayout(QRect(0, 0, width, 0), True)
    def setGeometry(self, rect): super().setGeometry(rect); self._doLayout(rect, False)
    def sizeHint(self): return self.minimumSize()
    
    def minimumSize(self):
        size = QSize()
        for item in self.itemList: size = size.expandedTo(item.minimumSize())
        m = 2 * self.contentsMargins().top()
        return size + QSize(m, m)

    def _doLayout(self, rect, testOnly):
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self.itemList:
            space_x, space_y = self.spacing(), self.spacing()
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > rect.right() and line_height > 0:
                x, y, line_height = rect.x(), y + line_height + space_y, 0
                next_x = x + item.sizeHint().width() + space_x
            if not testOnly: item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x, line_height = next_x, max(line_height, item.sizeHint().height())
        return y + line_height - rect.y()

# --- 2. 搜索框 ---
# main.py 中修改 TokenSearchBox 类
class TokenSearchBox(QFrame):
    textChanged = Signal(str)
    tokenRemoved = Signal(int)  # 修改信号，传递被删除的 tag_id
    
    def __init__(self):
        super().__init__()
        self.setObjectName("SearchBoxShell")
        self.setStyleSheet("""
            #SearchBoxShell { background: white; border: 1px solid #ccc; border-radius: 8px; min-height: 42px; } 
            #SearchBoxShell:focus-within { border-color: #0078d4; border-width: 2px; }
        """)
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(10, 0, 10, 0)
        self.main_layout.setSpacing(5)

        # 用于存放多个已选标签的容器
        self.token_container = QWidget()
        self.token_layout = QHBoxLayout(self.token_container)
        self.token_layout.setContentsMargins(0, 0, 0, 0)
        self.token_layout.setSpacing(5)
        self.main_layout.addWidget(self.token_container)

        self.input = QLineEdit()
        self.input.setPlaceholderText("搜索作品或过滤列表...")
        self.input.setStyleSheet("border: none; background: transparent; font-size: 15px;")
        self.input.textChanged.connect(lambda t: self.textChanged.emit(t))
        self.main_layout.addWidget(self.input)

        self.count_label = QLabel("共 0 项")
        self.count_label.setStyleSheet("color: #888; font-size: 13px; margin-right: 5px;")
        self.main_layout.addWidget(self.count_label)

        self.input.installEventFilter(self)

    def set_count(self, count):
        self.count_label.setText(f"共 {count} 项")

    def add_filter_token(self, tag_id, text, color_hex):
        """新增一个标签 Token"""
        # 检查是否已存在
        for i in range(self.token_layout.count()):
            if self.token_layout.itemAt(i).widget().property("tag_id") == tag_id:
                return

        token = QPushButton(f"{text}  ✕")
        token.setProperty("tag_id", tag_id)
        token.setStyleSheet(f"""
            QPushButton {{
                background: {color_hex}; color: white; border-radius: 12px; 
                font-weight: bold; padding: 2px 10px; height: 24px; border: none;
            }}
            QPushButton:hover {{ background: rgba(0,0,0,0.2); }}
        """)
        token.clicked.connect(lambda: self.tokenRemoved.emit(tag_id))
        self.token_layout.addWidget(token)
        self.input.setPlaceholderText("")

    def remove_filter_token(self, tag_id):
        """移除指定标签 Token"""
        for i in range(self.token_layout.count()):
            w = self.token_layout.itemAt(i).widget()
            if w.property("tag_id") == tag_id:
                self.token_layout.takeAt(i)
                w.deleteLater()
                break
        if self.token_layout.count() == 0:
            self.input.setPlaceholderText("搜索作品或过滤列表...")

    def clear_all_tokens(self):
        while self.token_layout.count():
            w = self.token_layout.takeAt(0).widget()
            if w: w.deleteLater()
        self.input.setPlaceholderText("搜索作品或过滤列表...")

    def eventFilter(self, obj, event):
        if obj == self.input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Backspace and self.input.text() == "" and self.token_layout.count() > 0:
                # 退格键删除最后一个标签
                last_idx = self.token_layout.count() - 1
                last_tag_id = self.token_layout.itemAt(last_idx).widget().property("tag_id")
                self.tokenRemoved.emit(last_tag_id)
                return True
        return super().eventFilter(obj, event)

# --- 3. 标签药丸 ---
class TagChip(QWidget):
    def __init__(self, tag_id, tag_name, group_name, parent_app, color, parent_folder_id=None):
        super().__init__()
        self.tag_id, self.tag_name, self.group_name, self.parent_app, self.color, self.parent_folder_id = tag_id, tag_name, group_name, parent_app, color, parent_folder_id
        layout = QHBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        self.main_btn = QPushButton(tag_name); self.main_btn.setFixedHeight(30); self.main_btn.setCursor(Qt.PointingHandCursor)
        self.more_btn = QPushButton("⋮"); self.more_btn.setFixedWidth(34); self.more_btn.setFixedHeight(30); self.more_btn.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.main_btn); layout.addWidget(self.more_btn)
        self.update_chip_style()
        self.main_btn.clicked.connect(lambda: self.parent_app.jump_to_tag(self.tag_id, self.tag_name, self.color))
        self.more_btn.clicked.connect(self.show_context_menu)
        self.main_btn.mouseMoveEvent = self.on_mouse_move

    def update_chip_style(self):
        base_style = f"background: {self.color}; color: white; border: none; font-weight: bold;"
        self.main_btn.setStyleSheet(f"QPushButton {{ {base_style} border-top-left-radius: 15px; border-bottom-left-radius: 15px; padding-left: 14px; padding-right: 10px; }} QPushButton:hover {{ background-color: rgba(0,0,0,0.1); }}")
        self.more_btn.setStyleSheet(f"QPushButton {{ {base_style} border-top-right-radius: 15px; border-bottom-right-radius: 15px; border-left: 2px solid rgba(255,255,255,0.45); font-size: 28px; font-weight: bold; padding-bottom: 4px; }} QPushButton:hover {{ background-color: rgba(0, 0, 0, 0.15); }}")

    def show_context_menu(self):
        menu = QMenu(self); menu.setStyleSheet(MENU_STYLE)
        a_show = menu.addAction("显示此标签文件")
        if self.parent_folder_id:
            a_rem = menu.addAction("从此作品移除")
            res = menu.exec(QCursor.pos())
            if res == a_show: self.parent_app.jump_to_tag(self.tag_id, self.tag_name, self.color)
            elif res == a_rem: self.parent_app.remove_tag_from_folder(self.tag_id, self.parent_folder_id)
        else:
            a_ed, a_del = menu.addAction("编辑标签名称"), menu.addAction("删除此标签")
            res = menu.exec(QCursor.pos())
            if res == a_show: self.parent_app.jump_to_tag(self.tag_id, self.tag_name, self.color)
            elif res == a_ed: self.parent_app.edit_tag(self.tag_id, self.tag_name)
            elif res == a_del: self.parent_app.delete_tag(self.tag_id, self.tag_name)

    def on_mouse_move(self, e):
        if not (e.buttons() & Qt.LeftButton): return
        drag = QDrag(self); mime = QMimeData()
        if self.parent_folder_id: mime.setText(f"REMOVE_TAG_DATA:{self.tag_id}:{self.parent_folder_id}")
        else: mime.setText(f"ADD_TAG_DATA:{self.tag_id}:{self.tag_name}:{self.color}")
        drag.setMimeData(mime); drag.exec(Qt.CopyAction)

# --- 4. 标签组标题行 ---
class TagGroupHeader(QWidget):
    def __init__(self, group_name, parent_app):
        super().__init__()
        self.group_name = group_name; self.parent_app = parent_app
        layout = QHBoxLayout(self); layout.setContentsMargins(0, 15, 0, 5)
        label = QLabel(group_name); label.setStyleSheet("font-weight: bold; color: #444; font-size: 14px; text-transform: uppercase;")
        btn = QPushButton("⋮"); btn.setFixedSize(30, 30); btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("QPushButton { border: none; color: #999; font-size: 32px; font-weight: bold; } QPushButton:hover { color: #0078d4; background: #eee; border-radius: 6px; }")
        layout.addWidget(label); layout.addStretch(); layout.addWidget(btn)
        btn.clicked.connect(self.show_menu)

    def show_menu(self):
        menu = QMenu(self); menu.setStyleSheet(MENU_STYLE)
        a1, a2, a3 = menu.addAction("在此组下新增标签"), menu.addAction("编辑组名"), menu.addAction("删除组")
        res = menu.exec(QCursor.pos())
        if res == a1: self.parent_app.add_tag_to_group(self.group_name)
        elif res == a2: self.parent_app.edit_group(self.group_name)
        elif res == a3: self.parent_app.delete_group(self.group_name)

# --- 5. 作品卡片 (项目展示) ---
class FolderCard(QFrame):
    def __init__(self, fid, name, path, thumb, tags_data, parent_app, index_num=0):
        super().__init__()
        self.fid, self.parent_app, self.abs_path = fid, parent_app, path
        self.setAcceptDrops(True)
        self.setObjectName("FolderCard"); self.setAttribute(Qt.WA_StyledBackground, True)
        self.base_qss = "background-color: white; border-radius: 10px;"
        self.idle_qss, self.selected_qss = "border: 2px solid transparent;", "border: 2px solid #0078d4;"
        self.setStyleSheet(f"#FolderCard {{ {self.base_qss} {self.idle_qss} }}")
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_right_click_menu)
        
        main_layout = QHBoxLayout(self); main_layout.setContentsMargins(12, 12, 12, 12)

        # --- 新增：序号标签 ---
        self.index_label = QLabel(str(index_num))
        self.index_label.setFixedWidth(30) # 固定宽度保证对齐
        self.index_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #bbb;")
        self.index_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.index_label)
        # --------------------

        self.img = QLabel()
        self.img.setFixedSize(170, 115)
        # 核心：设置内容居中对齐
        self.img.setAlignment(Qt.AlignCenter) 
        self.img.setStyleSheet("background: #f0f0f0; border-radius: 6px; border: 1px solid #ddd;")
        if thumb and os.path.exists(thumb): self.img.setPixmap(QPixmap(thumb).scaled(170, 115, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        main_layout.addWidget(self.img)
        
        info_layout = QVBoxLayout(); info_layout.setSpacing(4)
        info_layout.addWidget(QLabel(name, styleSheet="font-size: 15px; font-weight: bold; color: #222;"))
        info_layout.addWidget(QLabel(path, styleSheet="font-size: 11px; color: #888;"))
        
        self.tag_container = QWidget(); self.tag_container.setStyleSheet("background: transparent;")
        self.flow_layout = FlowLayout(self.tag_container, spacing=8)
        
        cmap = parent_app.get_group_color_map()
        for tid, tn, group in tags_data: self.add_tag_to_ui(tid, tn, group, cmap.get(group, "#444"))
        
        info_layout.addWidget(self.tag_container); main_layout.addLayout(info_layout)
    
    def show_right_click_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLE)
        
        action_rename = menu.addAction("✏️ 更改目录名")
        action_change_thumb = menu.addAction("🖼️ 更换预览图")
        action_open_folder = menu.addAction("📂 打开文件夹")
        menu.addSeparator() # 添加分割线
        action_delete = menu.addAction("❌ 删除此作品") # 新增删除选项
        
        res = menu.exec(QCursor.pos())
        if res == action_rename:
            old_path = Path(self.abs_path)
            new_name, ok = QInputDialog.getText(self, "重命名目录", "请输入新名称:", text=old_path.name)
            if ok and new_name.strip() and new_name != old_path.name:
                new_path = old_path.parent / new_name.strip()
                try:
                    # 1. 物理重命名
                    os.rename(str(old_path), str(new_path))
                    # 2. 更新数据库
                    with sqlite3.connect(self.parent_app.engine.db_path) as conn:
                        conn.execute(
                            "UPDATE folders SET name = ?, abs_path = ? WHERE id = ?",
                            (new_name, str(new_path), self.fid)
                        )
                    # 3. 刷新中栏以显示新名称和路径
                    self.parent_app.refresh_mid_list()
                except Exception as e:
                    QMessageBox.critical(self, "重命名失败", f"无法重命名文件夹：\n{str(e)}")
        elif res == action_change_thumb:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "选择预览图", "", "Images (*.jpg *.jpeg *.png *.webp *.bmp)"
            )
            if file_path and self.parent_app.engine:
                new_thumb = self.parent_app.engine.update_folder_thumbnail(self.fid, file_path)
                if new_thumb:
                    # 局部刷新预览图，无需重新加载整个列表
                    self.img.setPixmap(QPixmap(new_thumb).scaled(
                        170, 115, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    ))
        
        elif res == action_open_folder:
            if os.path.exists(self.abs_path):
                os.startfile(self.abs_path)

        elif res == action_delete:
            self.parent_app.delete_folder_entry(self.fid, self.abs_path)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self.abs_path and os.path.exists(self.abs_path):
            os.startfile(self.abs_path)
        super().mouseDoubleClickEvent(event)

    def add_tag_to_ui(self, tid, name, group, color):
        for i in range(self.flow_layout.count()):
            w = self.flow_layout.itemAt(i).widget()
            if isinstance(w, TagChip) and int(w.tag_id) == int(tid): return

        order_map = self.parent_app.get_group_order_map()
        new_weight = order_map.get(group, 999)

        insert_idx = self.flow_layout.count()
        for i in range(self.flow_layout.count()):
            existing_widget = self.flow_layout.itemAt(i).widget()
            if isinstance(existing_widget, TagChip):
                existing_weight = order_map.get(existing_widget.group_name, 999)
                if new_weight < existing_weight:
                    insert_idx = i
                    break
                elif new_weight == existing_weight:
                    if name < existing_widget.tag_name:
                        insert_idx = i
                        break

        chip = TagChip(tid, name, group, self.parent_app, color, parent_folder_id=self.fid)
        self.flow_layout.insertWidget(insert_idx, chip)
        
        # 强制刷新容器大小以适配新插入的药丸
        self.tag_container.adjustSize()
        self.tag_container.update()

    def remove_tag_by_id(self, tid):
        # 必须缩进 4 个空格
        for i in range(self.flow_layout.count()):
            w = self.flow_layout.itemAt(i).widget()
            if isinstance(w, TagChip) and int(w.tag_id) == int(tid): 
                # 找到匹配的标签药丸后执行删除
                item = self.flow_layout.takeAt(i)
                if item.widget():
                    item.widget().deleteLater()
                
                # 核心：局部触发布局刷新，避免全量刷新
                self.flow_layout.invalidate()
                self.tag_container.adjustSize()
                break

    def set_selection_style(self, sel): 
        self.setStyleSheet(f"#FolderCard {{ {self.base_qss} {self.selected_qss if sel else self.idle_qss} }}")

# --- 6. 文件库卡片 ---
class LibraryCard(QFrame):
    def __init__(self, name, path, is_active=False):
        super().__init__()
        self.setObjectName("LibraryCard"); self.setAttribute(Qt.WA_StyledBackground, True)
        base = "background-color: white; border-radius: 8px; margin: 2px;"
        border = "border: 2px solid #0078d4;" if is_active else "border: 1px solid #eee;"
        self.setStyleSheet(f"#LibraryCard {{ {base} {border} }}")
        
        layout = QVBoxLayout(self); layout.setContentsMargins(15, 12, 15, 12); layout.setSpacing(2)
        name_label = QLabel(f"📁 {name}"); name_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #333; border: none;")
        path_label = QLabel(path); path_label.setStyleSheet("font-size: 11px; color: #888; border: none;")
        layout.addWidget(name_label); layout.addWidget(path_label)

class SmoothScroller(QObject):
    def __init__(self, scroll_bar):
        super().__init__()
        self.scroll_bar = scroll_bar
        self.ani = QVariantAnimation(self)
        self.ani.setEasingCurve(QEasingCurve.OutCubic)
        self.ani.setDuration(300) # 稍微缩短时长提升跟手感
        self.ani.valueChanged.connect(self._handle_value_changed)
        self.target_value = self.scroll_bar.value() # 新增：记录最终目标值

    def _handle_value_changed(self, value):
        if value is not None:
            self.scroll_bar.setValue(int(value))

    def scroll_to(self, delta):
        # 1. 获取当前正在运行的起始点
        current_ani_val = self.ani.currentValue()
        if self.ani.state() == QVariantAnimation.Running and current_ani_val is not None:
            start = current_ani_val
        else:
            start = self.scroll_bar.value()
            self.target_value = start # 确保目标值从当前位置开始计算

        # 2. 关键：在“最终目标值”基础上累加，而不是在当前位置累加
        self.target_value = max(self.scroll_bar.minimum(), 
                                min(self.scroll_bar.maximum(), self.target_value - delta))
        
        # 3. 如果已经到达边界，不执行动画
        if abs(start - self.target_value) < 0.1:
            return

        # 4. 更新动画
        self.ani.stop()
        self.ani.setStartValue(float(start))
        self.ani.setEndValue(float(self.target_value))
        self.ani.start()

# --- 7. 主窗口 ---
class SimpleTagApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MyTagManager"); self.resize(1600, 950); self.setAcceptDrops(True)
        
        # 1. 先构建 UI 组件
        self.init_ui()
        
        # 2. 关键配置：开启像素级滚动（必须在 init_ui 之后，此时 list_widget 已创建）
        self.list_widget.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        # 优化视口性能，减少滚动时的闪烁
        self.list_widget.viewport().setAttribute(Qt.WA_StaticContents)
        
        # 3. 初始化平滑滚动器并安装过滤器
        # 注意：如果觉得滚动太慢，可以在 eventFilter 里给 delta 乘个系数
        self.scroller = SmoothScroller(self.list_widget.verticalScrollBar())
        self.list_widget.viewport().installEventFilter(self)

        self.global_db = os.path.join(os.path.dirname(__file__), "global_config.db")
        self.init_global_config()
        self.db_root = self.get_last_library()
        self.engine = LibraryEngine(self.db_root) if self.db_root else None
        self.preset_colors = ["#2C3E50", "#27AE60", "#C0392B", "#8E44AD", "#D35400", "#2980B9", "#16A085", "#7F8C8D"]
        self.current_sort_mode = "名称"
        self.current_filter_tag_ids = []
        
        self.refresh_library_list()
        self.refresh_left_tag_library()
        self.refresh_mid_list()
        
        self.switch_left_view(1)

    def on_sort_changed(self, text):
        """[新增] 处理排序切换"""
        self.current_sort_mode = text
        self.refresh_mid_list()     

    def init_global_config(self):
        with sqlite3.connect(self.global_db) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS libraries (id INTEGER PRIMARY KEY, name TEXT, path TEXT UNIQUE)")
            # 新增：用于存储全局 KV 配置的表
            conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            
            default_p = os.path.abspath(os.path.join(os.path.dirname(__file__), "libraries", "Default_Library"))
            if not os.path.exists(default_p): os.makedirs(default_p)
            conn.execute("INSERT OR IGNORE INTO libraries (name, path) VALUES (?, ?)", ("默认库", default_p))
    
    def eventFilter(self, source, event):
        if hasattr(self, 'list_widget') and source == self.list_widget.viewport():
            if event.type() == QEvent.Wheel:
                # 适当放大 delta (例如 1.5倍)，能显著提升视觉上的“高刷”丝滑感
                delta = event.angleDelta().y() * 1.5
                self.scroller.scroll_to(delta)
                return True
        return super().eventFilter(source, event)

    def get_last_library(self):
        with sqlite3.connect(self.global_db) as conn:
            # 优先从 settings 表读取上次记录的路径
            res = conn.execute("SELECT value FROM settings WHERE key='last_library'").fetchone()
            if res and os.path.exists(res[0]):
                return res[0]
            # 如果没记录，则回退到库列表的第一项
            res = conn.execute("SELECT path FROM libraries LIMIT 1").fetchone()
            return res[0] if res else None

    def get_group_order_map(self):
        m = {}
        if not self.engine: return m
        with sqlite3.connect(self.engine.db_path) as conn:
            for i, (g,) in enumerate(conn.execute("SELECT name FROM tag_groups ORDER BY id")):
                m[g] = i
        return m

    def init_ui(self):
        splitter = QSplitter(Qt.Horizontal); self.setCentralWidget(splitter)
        splitter.setHandleWidth(1); splitter.setStyleSheet("QSplitter::handle { background-color: #eee; }")
        
        self.left_panel = QWidget(); l_layout = QVBoxLayout(self.left_panel); l_layout.setContentsMargins(0, 0, 0, 0)
        self.left_panel.setMinimumWidth(350) 
        
        header_widget = QWidget(); header_layout = QHBoxLayout(header_widget); header_layout.setContentsMargins(20, 15, 20, 5)
        self.left_title = QLabel("文件库管理"); self.left_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #222;")
        self.global_more = QPushButton("⋮"); self.global_more.setFixedSize(36, 36); self.global_more.setCursor(Qt.PointingHandCursor)
        self.global_more.setStyleSheet("QPushButton { border: none; font-size: 34px; color: #666; font-weight: bold; } QPushButton:hover { background: #eee; border-radius: 6px; }")
        header_layout.addWidget(self.left_title); header_layout.addStretch(); header_layout.addWidget(self.global_more)
        l_layout.addWidget(header_widget)
        
        self.stack = QStackedWidget()
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.NoFrame)
        self.lib_container = QWidget(); self.lib_vbox = QVBoxLayout(self.lib_container); self.lib_vbox.setAlignment(Qt.AlignTop)
        self.lib_vbox.setContentsMargins(20, 0, 20, 0); self.scroll.setWidget(self.lib_container)
        
        self.lib_list_widget = QListWidget()
        self.lib_list_widget.setStyleSheet("""
            QListWidget { border: none; background: #f8f9fa; outline: none; } 
            QListWidget::item { padding: 4px; }
            QListWidget::item:selected { background: transparent; }
        """)
        self.lib_list_widget.itemClicked.connect(self.on_library_item_clicked)
        self.lib_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lib_list_widget.customContextMenuRequested.connect(self.show_library_context_menu)
        
        self.stack.addWidget(self.scroll) 
        self.stack.addWidget(self.lib_list_widget) 
        l_layout.addWidget(self.stack)

        nav_bar = QFrame(); nav_bar.setFixedHeight(50); nav_bar.setStyleSheet("background: #f0f0f0; border-top: 1px solid #ddd;")
        nav_layout = QHBoxLayout(nav_bar); nav_layout.setContentsMargins(5, 5, 5, 5)
        self.btn_nav_libs = QPushButton(" 文件库 ")
        self.btn_nav_tags = QPushButton(" 标签库 ")
        for b in [self.btn_nav_libs, self.btn_nav_tags]:
            b.setStyleSheet(NAV_BTN_STYLE); nav_layout.addWidget(b)
        self.btn_nav_tags.clicked.connect(lambda: self.switch_left_view(0))
        self.btn_nav_libs.clicked.connect(lambda: self.switch_left_view(1))
        l_layout.addWidget(nav_bar)
        splitter.addWidget(self.left_panel)

        self.mid_panel = QWidget(); m_layout = QVBoxLayout(self.mid_panel); m_layout.setContentsMargins(15, 15, 15, 15)
        self.search_box = TokenSearchBox(); self.search_box.textChanged.connect(lambda _: self.refresh_mid_list())
        self.search_box.tokenRemoved.connect(self.remove_single_filter); m_layout.addWidget(self.search_box)

        # --- [样式增强版] 排序控制栏 ---
        sort_layout = QHBoxLayout()
        sort_layout.setContentsMargins(10, 5, 10, 5) # 增加间距使其不拥挤
        
        sort_label = QLabel("排序:")
        sort_label.setStyleSheet("color: #888; font-size: 12px; font-weight: bold;")
        
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["名称", "数据库顺序"])
        self.sort_combo.setFixedWidth(110)
        
        # 应用与项目导航按钮和菜单一致的风格
        self.sort_combo.setStyleSheet("""
            QComboBox {
                border: 1px solid #ddd;
                border-radius: 6px;
                padding: 4px 12px;
                background: #f9f9f9;
                color: #555;
                font-size: 13px;
            }
            QComboBox:hover {
                background: #f0f0f0;
                border-color: #ccc;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            /* 下拉列表容器样式 (对应 MENU_STYLE) */
            QAbstractItemView {
                border: 1px solid #ddd;
                background: white;
                selection-background-color: #0078d4;
                selection-color: white;
                outline: none;
            }
        """)
        
        # 让下拉列表项的高度和菜单一致
        self.sort_combo.view().setStyleSheet("QAbstractItemView::item { min-height: 30px; padding-left: 10px; }")
        
        self.sort_combo.setCurrentText("名称")
        self.sort_combo.currentTextChanged.connect(self.on_sort_changed)
        
        sort_layout.addStretch()
        sort_layout.addWidget(sort_label)
        sort_layout.addWidget(self.sort_combo)
        m_layout.addLayout(sort_layout)
        # -----------------------
        
        self.list_widget = QListWidget(); self.list_widget.setSelectionMode(QListWidget.ExtendedSelection); self.list_widget.setSpacing(10)
        self.list_widget.setStyleSheet("""
    QListWidget { 
        border: none; 
        background: #fdfdfd; 
        outline: none; 
    }
    QListWidget::item:selected { 
        background: transparent; /* 选中时背景透明 */
        border: none;            /* 移除边框 */
        color: initial;          /* 保持文字颜色不变 */
    }
    QListWidget::item:hover {
        background: transparent; /* 如果你也不想要悬停时的灰色背景，可以加上这句 */
    }
""")
        self.list_widget.itemSelectionChanged.connect(self._sync_card_styles); m_layout.addWidget(self.list_widget)

        btns = QHBoxLayout(); b1, b2 = QPushButton("扫描父目录"), QPushButton("添加单独目录")
        b1.setFixedHeight(35); b2.setFixedHeight(35)
        b1.clicked.connect(self.scan_parent_folder); b2.clicked.connect(self.add_single_folders); btns.addWidget(b1); btns.addWidget(b2); m_layout.addLayout(btns)
        splitter.addWidget(self.mid_panel); splitter.setStretchFactor(0, 1); splitter.setStretchFactor(1, 4)

    def switch_left_view(self, index):
        self.stack.setCurrentIndex(index)
        self.left_title.setText("标签库管理" if index == 0 else "文件库管理")
        self.btn_nav_tags.setProperty("active", "true" if index == 0 else "false")
        self.btn_nav_libs.setProperty("active", "true" if index == 1 else "false")
        try: self.global_more.clicked.disconnect()
        except: pass
        if index == 0: self.global_more.clicked.connect(self.show_global_menu)
        else: self.global_more.clicked.connect(self.show_library_global_menu)
        for b in [self.btn_nav_tags, self.btn_nav_libs]: b.style().unpolish(b); b.style().polish(b)

    def show_library_global_menu(self):
        menu = QMenu(self); menu.setStyleSheet(MENU_STYLE)
        menu.addAction("添加新文件库", self.create_new_library_in_local); menu.exec(QCursor.pos())

    def create_new_library_in_local(self):
        name, ok = QInputDialog.getText(self, "新建文件库", "请输入库名称:")
        if not ok or not name.strip(): return
        base_dir = os.path.dirname(os.path.abspath(__file__))
        libs_dir = os.path.join(base_dir, "libraries")
        if not os.path.exists(libs_dir): os.makedirs(libs_dir)
        new_lib_path = os.path.join(libs_dir, name.strip())
        if not os.path.exists(new_lib_path): os.makedirs(new_lib_path)
        with sqlite3.connect(self.global_db) as conn:
            conn.execute("INSERT OR IGNORE INTO libraries (name, path) VALUES (?, ?)", (name, new_lib_path))
        self.refresh_library_list()

    def refresh_library_list(self):
        self.lib_list_widget.clear()
        invalid_paths = []
        with sqlite3.connect(self.global_db) as conn:
            rows = conn.execute("SELECT id, name, path FROM libraries").fetchall()
            for lid, name, path in rows:
                if os.path.exists(path):
                    is_active = (self.db_root == path)
                    item = QListWidgetItem(); item.setSizeHint(QSize(0, 75)); item.setData(Qt.UserRole, path)
                    self.lib_list_widget.addItem(item)
                    self.lib_list_widget.setItemWidget(item, LibraryCard(name, path, is_active))
                else: invalid_paths.append(path)
            if invalid_paths:
                conn.executemany("DELETE FROM libraries WHERE path=?", [(p,) for p in invalid_paths])
        if not self.db_root and self.lib_list_widget.count() > 0:
            self.on_library_item_clicked(self.lib_list_widget.item(0))

    def on_library_item_clicked(self, item):
        path = item.data(Qt.UserRole)
        if path and os.path.exists(path):
            self.db_root = path
            self.engine = LibraryEngine(path)
            
            # 保存到全局配置
            with sqlite3.connect(self.global_db) as conn:
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_library', ?)", (path,))
            
            self.current_filter_tag_ids = [] # 修正原代码中的变量名残缺
            self.search_box.clear_all_tokens() # 修正原代码方法调用
            self.refresh_library_list()
            self.refresh_left_tag_library()
            self.refresh_mid_list()

    # main.py 中 SimpleTagApp 类的方法
    def show_library_context_menu(self, pos):
        item = self.lib_list_widget.itemAt(pos)
        path = item.data(Qt.UserRole) if item else None
        if not path: return
        
        menu = QMenu()
        menu.setStyleSheet(MENU_STYLE)
        a_rem = menu.addAction("⚠️ 彻底删除库（物理删除文件夹）")
        
        if menu.exec(QCursor.pos()) == a_rem:
            confirm = QMessageBox.question(
                self, "确认物理删除", 
                f"此操作将永久删除文件夹：\n{path}\n确认吗？",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if confirm == QMessageBox.Yes:
                try: 
                    # 1. 如果是当前正在使用的库，必须先彻底切断联系
                    if self.db_root == path:
                        if self.engine:
                            self.engine.close() # 调用刚才添加的关闭方法
                        self.engine = None
                        self.db_root = None
                        # 必须清空界面卡片，因为卡片持有图片文件句柄
                        self.list_widget.clear()
                        self.refresh_left_tag_library()

                    # 2. 关键：强制释放资源
                    gc.collect() # 强制 Python 垃圾回收
                    QApplication.processEvents() # 让 Qt 处理完当前的 UI 刷新事件

                    # 3. 执行删除
                    if os.path.exists(path):
                        # 处理 Windows 下只读文件导致无法删除的问题
                        def onerror(func, path, exc_info):
                            import stat
                            os.chmod(path, stat.S_IWRITE)
                            func(path)
                        
                        shutil.rmtree(path, onerror=onerror) 
                        
                    # 4. 从全局配置数据库中移除记录
                    with sqlite3.connect(self.global_db) as conn:
                        conn.execute("DELETE FROM libraries WHERE path=?", (path,))
                    
                    # 5. 刷新界面
                    self.refresh_library_list()
                    QMessageBox.information(self, "成功", "文件夹已从硬盘删除")
                    
                except Exception as e:
                    QMessageBox.critical(self, "错误", f"无法物理删除文件夹，请尝试手动删除：\n{str(e)}")

    def show_global_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLE)
        menu.addAction("新建标签组", self.define_new_group)
        menu.addSeparator() # 分割线
        menu.addAction("导出标签库", self.handle_export_tags)
        menu.addAction("导入标签库", self.handle_import_tags)
        menu.exec(QCursor.pos())

    def define_new_group(self):
        g, ok = QInputDialog.getText(self, "新标签组", "名称:")
        if ok and g and self.engine and self.engine.add_new_group(g): self.refresh_left_tag_library()

    # main.py 约 560 行左右

    def add_tag_to_group(self, group):
        # 这一行必须比 def 缩进一级
        n, ok = QInputDialog.getText(self, "新增标签", f"在 [{group}] 下创建:")
        if ok and n:
            with sqlite3.connect(self.engine.db_path) as conn:
                cursor = conn.cursor()
                
                # 1. 获取当前组内最大的排序值
                cursor.execute("SELECT MAX(sort_order) FROM tag_definitions WHERE category = ?", (group,))
                res = cursor.fetchone()
                # 如果组内没有标签，max_order 会是 None，此时设为 0
                max_order = res[0] if res and res[0] is not None else -1
                new_order = max_order + 1
                
                # 2. 插入新标签并带上排序值
                conn.execute(
                    "INSERT OR IGNORE INTO tag_definitions (category, name, sort_order) VALUES (?, ?, ?)", 
                    (group, n, new_order)
                )
            # 3. 刷新界面
            self.refresh_left_tag_library()

    def edit_group(self, old):
        n, ok = QInputDialog.getText(self, "编辑", "新名称:", text=old)
        if ok and n:
            with sqlite3.connect(self.engine.db_path) as conn:
                conn.execute("UPDATE tag_groups SET name=? WHERE name=?", (n, old))
                conn.execute("UPDATE tag_definitions SET category=? WHERE category=?", (n, old))
            self.refresh_left_tag_library(); self.refresh_mid_list()

    def delete_group(self, group):
        if QMessageBox.question(self, "删除", f"删除组 [{group}] 及其下所有标签？") == QMessageBox.Yes:
            self.engine.delete_group(group); self.refresh_left_tag_library(); self.refresh_mid_list()

    def refresh_left_tag_library(self):
        while self.lib_vbox.count():
            w = self.lib_vbox.takeAt(0).widget()
            if w: w.deleteLater()
        if not self.engine: return
        cmap = self.get_group_color_map()
        with sqlite3.connect(self.engine.db_path) as conn:
            all_groups = [r[0] for r in conn.execute("SELECT name FROM tag_groups ORDER BY id").fetchall()]
            tags_raw = conn.execute("SELECT id, category, name FROM tag_definitions ORDER BY sort_order, name").fetchall()
            data = {g: [] for g in all_groups}
            for tid, group, name in tags_raw:
                if group in data: data[group].append((tid, name))
        for g in all_groups:
            self.lib_vbox.addWidget(TagGroupHeader(g, self))
            cont = QWidget(); flow = FlowLayout(cont, spacing=10)
            for tid, name in data.get(g, []): flow.addWidget(TagChip(tid, name, g, self, cmap.get(g, "#444")))
            self.lib_vbox.addWidget(cont)
        self.lib_vbox.addStretch()

    def get_group_color_map(self):
        m = {}
        if not self.engine: return m
        with sqlite3.connect(self.engine.db_path) as conn:
            for i, (g,) in enumerate(conn.execute("SELECT name FROM tag_groups ORDER BY id")):
                m[g] = self.preset_colors[i % len(self.preset_colors)]
        return m

    def refresh_mid_list(self):
        # --- 注意：以下所有代码相对于 def 必须缩进 4 个空格 ---
        if hasattr(self, 'scroller'):
            self.scroller.ani.stop()

        scroll_bar = self.list_widget.verticalScrollBar()
        current_scroll_pos = scroll_bar.value()
        self.list_widget.setUpdatesEnabled(False)
        self.list_widget.clear()
        
        if not self.engine: 
            self.search_box.set_count(0)
            self.list_widget.setUpdatesEnabled(True)
            return
            
        txt = self.search_box.input.text().strip()
        
        with sqlite3.connect(self.engine.db_path) as conn:
            # 基础查询语句
            q = "SELECT f.id, f.name, f.abs_path, f.thumb_path FROM folders f"
            params = []
            conds = []

            # 1. 处理文本搜索
            if txt: 
                conds.append("(f.name LIKE ? OR f.abs_path LIKE ?)")
                params.extend([f"%{txt}%", f"%{txt}%"])

            # 2. 处理多标签交集过滤 (核心修改点)
            if self.current_filter_tag_ids:
                # 这里的逻辑是：找出那些 拥有所有选中标签 的文件夹
                placeholders = ','.join(['?'] * len(self.current_filter_tag_ids))
                tag_cond = f"""
                    f.id IN (
                        SELECT folder_id FROM folder_tags 
                        WHERE tag_id IN ({placeholders})
                        GROUP BY folder_id 
                        HAVING COUNT(DISTINCT tag_id) = ?
                    )
                """
                conds.append(tag_cond)
                params.extend(self.current_filter_tag_ids)
                params.append(len(self.current_filter_tag_ids))

            if conds:
                q += " WHERE " + " AND ".join(conds)
            
            # 3. [核心修改] 处理排序逻辑
            if self.current_sort_mode == "名称":
                # COLLATE NOCASE 确保不区分大小写排序
                q += " ORDER BY f.name COLLATE NOCASE ASC"
            elif self.current_sort_mode == "数据库顺序":
                q += " ORDER BY f.id ASC"
            
            
            # 执行查询
            results = conn.execute(q, params).fetchall()
            self.search_box.set_count(len(results))

            # 渲染结果列表
            for index, (fid, name, path, thumb) in enumerate(results, start=1): # 使用 enumerate 获取序号
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT td.id, td.name, td.category 
                    FROM tag_definitions td 
                    JOIN folder_tags ft ON td.id = ft.tag_id 
                    JOIN tag_groups tg ON td.category = tg.name
                    WHERE ft.folder_id = ?
                    ORDER BY tg.id, td.sort_order, td.name
                """, (fid,))
                
                tags_info = cursor.fetchall() # 提取查询结果
                
                it = QListWidgetItem()
                it.setSizeHint(QSize(0, 140))
                self.list_widget.addItem(it)

                # 关键：在这里传入 index
                card = FolderCard(fid, name, path, thumb, tags_info, self, index_num=index)
                self.list_widget.setItemWidget(it, card)


        self.list_widget.setUpdatesEnabled(True)
        # 保持滚动条位置
        QTimer.singleShot(0, lambda: scroll_bar.setValue(current_scroll_pos))

    def remove_tag_from_folder(self, tid, fid):
        # 1. 数据库层面删除关联
        with sqlite3.connect(self.engine.db_path) as conn:
            conn.execute("DELETE FROM folder_tags WHERE folder_id=? AND tag_id=?", (fid, tid))
            conn.commit()
            
        # 2. 如果当前正在根据此标签过滤，必须刷新中栏
        if hasattr(self, 'current_filter_tag_ids') and tid in self.current_filter_tag_ids:
            self.refresh_mid_list()
            return

        # 3. 否则，仅针对目标卡片执行局部 UI 移除（不重建整个列表）
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            card = self.list_widget.itemWidget(item)
            if card and card.fid == fid:
                card.remove_tag_by_id(tid)
                break

    def dropEvent(self, e):
        mime_data = e.mimeData()
        
        # --- 1. 处理系统外部拖入的文件/文件夹 (新增) ---
        if mime_data.hasUrls():
            added_any = False
            for url in mime_data.urls():
                # 确保是本地文件系统路径
                if url.isLocalFile():
                    path = url.toLocalFile()
                    # 严格判断拖入的是否为目录 (过滤掉单独的文件)
                    if os.path.isdir(path):
                        self.engine.add_single_folder(path)
                        added_any = True
            
            # 如果成功添加了至少一个目录，刷新中间的作品列表
            if added_any:
                self.refresh_mid_list()
            
            e.acceptProposedAction()
            return  # 外部拖拽处理完毕，直接 return，避免与下方标签系统冲突

        # --- 2. 处理应用内部的标签拖拽 (原逻辑保持不变) ---
        if mime_data.hasText():
            txt = mime_data.text()
            pos = self.list_widget.mapFrom(self, e.position().toPoint())
            item = self.list_widget.itemAt(pos)
            
            if txt.startswith("ADD_TAG_DATA:") and item:
                _, tid, tname, tcol = txt.split(":")
                card = self.list_widget.itemWidget(item)
                if card:
                    fid = card.fid
                    with sqlite3.connect(self.engine.db_path) as conn: 
                        conn.execute("INSERT OR IGNORE INTO folder_tags (folder_id, tag_id) VALUES (?,?)", (fid, tid))
                        group_name = conn.execute("SELECT category FROM tag_definitions WHERE id=?", (tid,)).fetchone()[0]
                    card.add_tag_to_ui(int(tid), tname, group_name, tcol)
                    e.acceptProposedAction()
            elif txt.startswith("REMOVE_TAG_DATA:") and not item:
                _, tid, fid = txt.split(":")
                self.remove_tag_from_folder(int(tid), int(fid))
                e.acceptProposedAction()

    def dragEnterEvent(self, e): 
        # 允许接收文本(标签系统) 或 URL(外部系统文件/文件夹)
        if e.mimeData().hasText() or e.mimeData().hasUrls():
            e.acceptProposedAction()
    
    def _sync_card_styles(self):
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i); c = self.list_widget.itemWidget(it)
            if c: c.set_selection_style(it.isSelected())
            
    def jump_to_tag(self, tid, tname, col): 
        if tid not in self.current_filter_tag_ids:
            self.current_filter_tag_ids.append(tid)
            self.search_box.add_filter_token(tid, tname, col)
            self.refresh_mid_list()
    
    def remove_single_filter(self, tid):
        if tid in self.current_filter_tag_ids:
            self.current_filter_tag_ids.remove(tid)
            self.search_box.remove_filter_token(tid)
            self.refresh_mid_list()

    def clear_filter(self): 
        self.current_filter_tag_ids = []
        self.search_box.clear_all_tokens()
        self.refresh_mid_list()
        
    def edit_tag(self, tid, old):
        n, ok = QInputDialog.getText(self, "编辑", "新名称:", text=old)
        if ok and n:
            with sqlite3.connect(self.engine.db_path) as conn: 
                conn.execute("UPDATE tag_definitions SET name=? WHERE id=?", (n, tid))
            self.refresh_left_tag_library(); self.refresh_mid_list()
            
    def delete_tag(self, tid, name):
        confirm = QMessageBox.question(self, "删除", f"确定删除 [{name}]？")
        if confirm != QMessageBox.Yes:
            return

        # 1. 立即从数据库执行删除 (如果数据量极大，可用 QThread，普通量级 sqlite 很快)
        if self.engine:
            with sqlite3.connect(self.engine.db_path) as conn:
                conn.execute("DELETE FROM folder_tags WHERE tag_id=?", (tid,))
                conn.execute("DELETE FROM tag_definitions WHERE id=?", (tid,))
                conn.commit()

        # 2. 局部刷新 UI：从左侧标签库中移除该药丸
        # 遍历左侧布局寻找并销毁对应的 TagChip
        for i in range(self.lib_vbox.count()):
            group_widget = self.lib_vbox.itemAt(i).widget()
            if isinstance(group_widget, QWidget) and not isinstance(group_widget, TagGroupHeader):
                # 这里的 group_widget 是承载 FlowLayout 的容器
                flow = group_widget.layout()
                for j in range(flow.count()):
                    chip = flow.itemAt(j).widget()
                    if isinstance(chip, TagChip) and int(chip.tag_id) == int(tid):
                        flow.takeAt(j)
                        chip.deleteLater()
                        break 

        # 3. 局部刷新 UI：从中间作品卡片中移除该药丸
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            card = self.list_widget.itemWidget(item)
            if card:
                card.remove_tag_by_id(tid)

        # 4. 如果当前正在过滤这个标签，则清除过滤状态
        # 4. 如果当前正在过滤这个标签，则将其从过滤列表中移除
        if hasattr(self, 'current_filter_tag_ids') and tid in self.current_filter_tag_ids:
            self.current_filter_tag_ids.remove(tid)
            # 同时更新搜索框的 Token 显示
            self.search_box.remove_filter_token(tid)
            # 刷新中栏结果
            self.refresh_mid_list()
            
    def scan_parent_folder(self):
        d = QFileDialog.getExistingDirectory(self, "扫描")
        if d: self.engine.scan_directory(d); self.refresh_mid_list()
        
    def add_single_folders(self):
        d = QFileDialog.getExistingDirectory(self, "添加")
        if d: self.engine.add_single_folder(d); self.refresh_mid_list()

    def handle_export_tags(self):
        if not self.engine: return
        path, _ = QFileDialog.getSaveFileName(self, "导出标签库", "tags_backup.json", "JSON Files (*.json)")
        if path:
            if self.engine.export_tags_structure(path):
                QMessageBox.information(self, "成功", "标签库已导出")
            else:
                QMessageBox.critical(self, "错误", "导出失败，请检查日志")

    def handle_import_tags(self):
        if not self.engine: return
        path, _ = QFileDialog.getOpenFileName(self, "导入标签库", "", "JSON Files (*.json)")
        if not path: return

        # 弹出模式选择
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("导入模式选择")
        msg_box.setText("请选择导入方式：")
        msg_box.setInformativeText("【合并】：保留现有标签，仅新增缺少的组和标签。\n"
                                   "【覆盖】：清空当前库所有标签和关联，完全以文件为准。")
        
        btn_merge = msg_box.addButton("合并导入", QMessageBox.ActionRole)
        btn_replace = msg_box.addButton("覆盖导入 (危险)", QMessageBox.ActionRole)
        msg_box.addButton("取消", QMessageBox.RejectRole)
        
        msg_box.exec()
        
        if msg_box.clickedButton() == btn_merge:
            mode = "merge"
        elif msg_box.clickedButton() == btn_replace:
            # 覆盖前再次确认
            confirm = QMessageBox.warning(self, "二次确认", "覆盖将清空当前库所有作品的标签记录，确定吗？", 
                                         QMessageBox.Yes | QMessageBox.No)
            if confirm == QMessageBox.No: return
            mode = "replace"
        else:
            return

        if self.engine.import_tags_structure(path, mode):
            self.refresh_left_tag_library()
            self.refresh_mid_list()
            QMessageBox.information(self, "成功", "标签库导入完成")
        else:
            QMessageBox.critical(self, "错误", "导入失败，文件格式可能不正确")

    
    def delete_folder_entry(self, fid, abs_path):
        """弹出删除确认对话框"""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("删除作品")
        msg_box.setText(f"确定要删除作品：\n{os.path.basename(abs_path)} 吗？")
        msg_box.setInformativeText("请选择处理方式：\n\n"
                                   "【仅移除记录】：从列表中移除，保留硬盘文件夹。\n"
                                   "【彻底删除】：直接删除硬盘上的物理文件夹（不可逆）！")
        
        btn_remove_only = msg_box.addButton("仅移除记录", QMessageBox.ActionRole)
        btn_delete_physical = msg_box.addButton("彻底删除物理目录", QMessageBox.DestructiveRole)
        msg_box.addButton("取消", QMessageBox.RejectRole)
        
        msg_box.exec()
        
        clicked = msg_box.clickedButton()
        
        if clicked == btn_remove_only:
            self._execute_folder_deletion(fid, abs_path, physical=False)
        elif clicked == btn_delete_physical:
            # 二次确认，防止手抖
            confirm = QMessageBox.warning(self, "高危操作确认", 
                                         "物理删除将永久移除该文件夹及其所有内容，确定吗？", 
                                         QMessageBox.Yes | QMessageBox.No)
            if confirm == QMessageBox.Yes:
                self._execute_folder_deletion(fid, abs_path, physical=True)

    def _execute_folder_deletion(self, fid, abs_path, physical=False):
        """执行具体的删除逻辑"""
        try:
            # 1. 如果需要物理删除物理目录
            if physical:
                if os.path.exists(abs_path):
                    # 处理可能存在的只读文件导致的删除失败
                    def onerror(func, path, exc_info):
                        import stat
                        os.chmod(path, stat.S_IWRITE)
                        func(path)
                    shutil.rmtree(abs_path, onerror=onerror)
            
            # 2. 数据库清理
            with sqlite3.connect(self.engine.db_path) as conn:
                # 删除标签关联
                conn.execute("DELETE FROM folder_tags WHERE folder_id = ?", (fid,))
                # 删除文件夹主记录
                conn.execute("DELETE FROM folders WHERE id = ?", (fid,))
                conn.commit()
            
            # 3. UI 局部刷新：从当前 list_widget 中移除对应的项
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                card = self.list_widget.itemWidget(item)
                if card and card.fid == fid:
                    self.list_widget.takeItem(i)
                    card.deleteLater()
                    break
            
            # 4. 更新搜索框显示的计数
            self.search_box.set_count(self.list_widget.count())
            self.refresh_mid_list()
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"删除失败：\n{str(e)}")

if __name__ == "__main__":
    app = QApplication(sys.argv); app.setStyle("Fusion"); window = SimpleTagApp(); window.show(); sys.exit(app.exec())


