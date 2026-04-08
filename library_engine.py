import os
import sqlite3
import hashlib
import json
from pathlib import Path
from PIL import Image
import ffmpeg

class LibraryEngine:
    def __init__(self, library_path):
        self.library_path = Path(library_path).absolute()
        self.db_path = self.library_path / "library.db"
        self.thumb_dir = self.library_path / "thumbnails"
        
        self.base_dir = Path(os.path.dirname(os.path.abspath(__file__)))
        self.ffmpeg_exe = str(self.base_dir / "ffmpeg.exe")
        
        self.library_path.mkdir(parents=True, exist_ok=True)
        self.thumb_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def close(self):
        """物理删除前必须调用，释放数据库文件句柄"""
        try:
            # 这里的 db_path 对应你 main.py 中使用的 metadata.db
            conn = sqlite3.connect(self.db_path)
            conn.close() 
            # 强制让 Python 释放可能的隐式连接池
        except:
            pass

    def _init_db(self):
        """初始化数据库结构，增加独立的标签组表"""
        with sqlite3.connect(self.db_path) as conn:
            # 1. 创建标签组独立表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tag_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                )
            """)
            
            # 2. 创建标签定义表 (增加外键关联)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tag_definitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT,
                    name TEXT,
                    sort_order INTEGER DEFAULT 0, -- 新增排序字段
                    UNIQUE(category, name),
                    FOREIGN KEY (category) REFERENCES tag_groups(name) ON DELETE CASCADE ON UPDATE CASCADE
                )
            """)
            
            # 3. 创建作品表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    abs_path TEXT UNIQUE,
                    thumb_path TEXT
                )
            """)
            
            # 4. 创建关联表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS folder_tags (
                    folder_id INTEGER,
                    tag_id INTEGER,
                    PRIMARY KEY (folder_id, tag_id)
                )
            """)
            
            # 数据迁移补丁：如果旧数据存在但 tag_groups 是空的，从标签表同步组名
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM tag_groups")
            if cursor.fetchone()[0] == 0:
                conn.execute("INSERT OR IGNORE INTO tag_groups (name) SELECT DISTINCT category FROM tag_definitions")
            
            conn.commit()

    def add_new_group(self, group_name):
        """显式创建新组"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("INSERT INTO tag_groups (name) VALUES (?)", (group_name,))
                return True
        except sqlite3.IntegrityError:
            return False

    def delete_group(self, group_name):
        """删除组及其下的所有标签"""
        with sqlite3.connect(self.db_path) as conn:
            # 获取该组下的标签 ID
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM tag_definitions WHERE category = ?", (group_name,))
            tag_ids = [r[0] for r in cursor.fetchall()]
            
            # 删除关联关系
            if tag_ids:
                placeholders = ','.join(['?'] * len(tag_ids))
                conn.execute(f"DELETE FROM folder_tags WHERE tag_id IN ({placeholders})", tag_ids)
            
            # 删除标签定义
            conn.execute("DELETE FROM tag_definitions WHERE category = ?", (group_name,))
            # 删除组
            conn.execute("DELETE FROM tag_groups WHERE name = ?", (group_name,))
            conn.commit()

    def scan_directory(self, root_path):
        """扫描目录并添加文件夹"""
        p = Path(root_path).absolute()
        for item in p.iterdir():
            if item.is_dir():
                self.add_single_folder(item)

    def add_single_folder(self, folder_path):
        """添加单个文件夹并生成缩略图"""
        path_obj = Path(folder_path).absolute()
        folder_name = path_obj.name
        abs_path = str(path_obj)
        
        # 生成/获取缩略图
        thumb_path = self.generate_thumbnail(path_obj)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO folders (name, abs_path, thumb_path) VALUES (?, ?, ?)",
                (folder_name, abs_path, str(thumb_path) if thumb_path else "")
            )

    def generate_thumbnail(self, folder_path):
        p = Path(folder_path)
        img_exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tiff'}
        vid_exts = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.mpeg', '.mpg', '.m4v'}
        
        # 针对网络路径，确保使用完整的绝对路径
        print(f"  > 正在处理预览图: {p.name}")
        try:
            all_files = list(p.rglob("*"))
        except Exception as e:
            print(f"无法读取目录内容: {e}")
            return None

        images = [f for f in all_files if f.suffix.lower() in img_exts]
        videos = [f for f in all_files if f.suffix.lower() in vid_exts]

        # 生成唯一的缓存文件名
        thumb_name = hashlib.md5(str(p).encode()).hexdigest() + ".jpg"
        target_thumb = self.thumb_dir / thumb_name

        # 如果缓存已存在，直接返回，避免重复生成
        if target_thumb.exists():
            print(f"    [跳过] 预览图已存在缓存中")
            return str(target_thumb)

        try:
            if images:
                # 随机选一张图片
                import random
                img_file = random.choice(images)
                with Image.open(img_file) as img:
                    img.thumbnail((400, 300))
                    img.convert("RGB").save(target_thumb, "JPEG")
                    print(f"    [成功] 已从图片生成预览")
                return str(target_thumb)
            
            elif videos:
                video_file = str(videos[0])
                # 检查 FFmpeg.exe 是否真的在那个位置
                if not os.path.exists(self.ffmpeg_exe):
                    print(f"致命错误: 找不到 FFmpeg.exe，路径为: {self.ffmpeg_exe}")
                    return None

                # 使用更稳健的方式调用 FFmpeg
                (
                    ffmpeg
                    .input(video_file, ss=1)
                    .filter('scale', 400, -1)
                    .output(str(target_thumb), vframes=1)
                    .overwrite_output()
                    .run(cmd=self.ffmpeg_exe, capture_stdout=True, capture_stderr=True)
                )
                print(f"    [成功] 已从视频抽帧生成预览")
                return str(target_thumb)
        except Exception as e:
            # 如果是 FFmpeg 报错，打印出更详细的信息
            print(f"生成预览失败 {folder_path}: {e}")
        
        return None
    
    def export_tags_structure(self, file_path):
        """导出标签分组结构为 JSON"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 获取所有组
                groups = conn.execute("SELECT name FROM tag_groups ORDER BY id").fetchall()
                data = {}
                for (g_name,) in groups:
                    # 获取该组下的所有标签名
                    tags = conn.execute(
                        "SELECT name FROM tag_definitions WHERE category = ? ORDER BY sort_order, name", (g_name,)
                    ).fetchall()
                    data[g_name] = [t[0] for t in tags]
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            print(f"导出失败: {e}")
            return False

    def import_tags_structure(self, file_path, mode="merge"):
        """
        导入标签结构。
        mode: 
          'merge': 合并模式，保留现有所有内容，仅新增。
          'replace': 覆盖模式，更新所有标签的分组归属，保留作品关联。
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                if mode == "replace":
                    # 1. 记录当前 JSON 中出现的所有标签名称
                    incoming_tag_names = []
                    for tags in data.values():
                        incoming_tag_names.extend(tags)
                    
                    # 2. 清空现有分组表
                    conn.execute("DELETE FROM tag_groups")
                    
                    # 3. 删除不在新 JSON 列表中的标签及其关联
                    if incoming_tag_names:
                        placeholders = ','.join(['?'] * len(incoming_tag_names))
                        conn.execute(f"""
                            DELETE FROM folder_tags 
                            WHERE tag_id IN (SELECT id FROM tag_definitions WHERE name NOT IN ({placeholders}))
                        """, incoming_tag_names)
                        conn.execute(f"DELETE FROM tag_definitions WHERE name NOT IN ({placeholders})", incoming_tag_names)
                    else:
                        conn.execute("DELETE FROM tag_definitions")
                        conn.execute("DELETE FROM folder_tags")

                # 4. 开始同步数据
                for g_name, tags in data.items():
                    conn.execute("INSERT OR IGNORE INTO tag_groups (name) VALUES (?)", (g_name,))
                    for idx,t_name in enumerate(tags):
                        cursor.execute("SELECT id FROM tag_definitions WHERE name = ?", (t_name,))
                        row = cursor.fetchone()
                        
                        if row:
                            # 存在则更新分类（保留ID从而保留关联）
                            conn.execute(
                                "UPDATE tag_definitions SET category = ?, sort_order = ? WHERE name = ?",
                                (g_name, idx, t_name)
                            )
                        else:
                            # 不存在则新建
                            conn.execute(
                                "INSERT INTO tag_definitions (category, name, sort_order) VALUES (?, ?, ?)",
                                (g_name, t_name, idx)
                            )
                conn.commit()
            return True  # <--- 请确保这一行缩进在 def 内部
            
        except Exception as e:
            print(f"导入失败: {e}")
            return False # <--- 请确保这一行缩进在 except 内部
    
    def delete_tag_data(self, tid):
        """仅处理数据库删除，不涉及 UI"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM folder_tags WHERE tag_id=?", (tid,))
            conn.execute("DELETE FROM tag_definitions WHERE id=?", (tid,))
            conn.commit()
    
    def update_folder_thumbnail(self, folder_id, new_img_path):
        """手动更换文件夹的预览图"""
        try:
            p = Path(new_img_path)
            # 生成新的唯一文件名
            thumb_name = hashlib.md5(f"manual_{folder_id}_{p.name}".encode()).hexdigest() + ".jpg"
            target_thumb = self.thumb_dir / thumb_name

            # 处理并保存新缩略图
            with Image.open(new_img_path) as img:
                img.thumbnail((400, 300))
                img.convert("RGB").save(target_thumb, "JPEG")

            # 更新数据库
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE folders SET thumb_path = ? WHERE id = ?",
                    (str(target_thumb), folder_id)
                )
            return str(target_thumb)
        except Exception as e:
            print(f"更换预览图失败: {e}")
            return None