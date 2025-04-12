import os
import sys
import json
import time
import zipfile
import glob
import re
import hashlib
import datetime
import threading
import requests
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import shutil

def resource_path(relative_path):
    """获取资源的绝对路径，兼容 PyInstaller 打包后的路径"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(get_exe_dir(), relative_path)

# ============================
# 配置与路径管理相关函数
# ============================
def get_exe_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(__file__)

CONFIG_PATH = os.path.join(get_exe_dir(), "config.json")

# 默认配置：默认保存目录为 exe 所在目录，历史记录为空
default_config = {
    "default_save_dir": get_exe_dir(),
    "upload_history": []
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            messagebox.showwarning("配置读取错误", str(e))
    return default_config.copy()

def save_config(config):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
    except Exception as e:
        messagebox.showwarning("配置保存错误", str(e))

config = load_config()  # 全局配置字典

# ============================
# 基础工具函数
# ============================

def generate_file_md5(file_path, blocksize=2**20):
    m = hashlib.md5()
    with open(file_path, "rb") as f:
        while chunk := f.read(blocksize):
            m.update(chunk)
    return m.hexdigest()

# ============================
# 上传文件相关函数
# ============================

def upload_file(file_path, log_func, progress_callback=lambda p: None):
    file_md5 = generate_file_md5(file_path)
    # 拼接上传 URL
    url = f"http://filesoss.yunzuoye.net/XHFileServer/file/upload/CA104004/{file_md5}"
    file_name = os.path.basename(file_path)
    size = os.path.getsize(file_path)
    try:
        with open(file_path, "rb") as file:
            fields = {"files": (file_name, file, "application/octet-stream")}
            encoder = MultipartEncoder(fields)
            monitor = MultipartEncoderMonitor(encoder, lambda mon: progress_callback(int((mon.bytes_read / mon.len) * 100)))
            date_str = datetime.datetime.now().strftime("%Y%m%d")
            headers = {
                "XueHai-MD5": file_md5,
                "Folder": f"yunketang/{date_str}",
                "Content-type": monitor.content_type
            }
            res = requests.post(url, headers=headers, data=monitor)
        if res.status_code == 200:
            body = res.json()
            fileId = body["uploadFileDTO"]["fileId"]
            log_func(f"[完成] 上传: {file_name} -> fileId: {fileId}")
            return {"index": None, "title": os.path.splitext(file_name)[0], "path": fileId, "md5": file_md5, "size": size}
        else:
            error_msg = res.json().get("msg", "上传失败")
            messagebox.showerror("上传失败", error_msg)
            return None
    except Exception as e:
        messagebox.showerror("上传异常", str(e))
        return None

# ============================
# 下载文件相关函数
# ============================

def download_file(file_id, output_path, progress_callback=lambda p: None):
    try:
        # 此处 file_id 实际上为下载 URL
        with requests.get(file_id, stream=True) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('Content-Length', 0))
            downloaded = 0
            chunk_size = 8192
            with open(output_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        progress = int((downloaded / total_size) * 100) if total_size else 100
                        progress_callback(progress)
        return output_path
    except Exception as e:
        messagebox.showerror("下载错误", str(e))
        return None

# ============================
# 分卷压缩与合并
# ============================

def split_zip_folder(folder_path, max_size=400*1024*1024):
    """
    将文件夹压缩为 ZIP 文件后进行分卷，返回各分卷文件的路径列表
    """
    base_name = os.path.basename(folder_path)
    temp_dir = os.path.join(get_exe_dir(), "temp_zip")
    os.makedirs(temp_dir, exist_ok=True)
    zip_path = os.path.join(temp_dir, f"{base_name}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                full_path = os.path.join(root, file)
                arcname = os.path.relpath(full_path, folder_path)
                zipf.write(full_path, arcname)
    parts = []
    with open(zip_path, "rb") as f:
        index = 0
        while chunk := f.read(max_size):
            part_name = os.path.join(temp_dir, f"{base_name}_part{index}.zip")
            with open(part_name, "wb") as pf:
                pf.write(chunk)
            parts.append(part_name)
            index += 1
    return parts

def merge_files(parts, output_file):
    with open(output_file, "wb") as outfile:
        # 依据文件名中 _partN 排序
        for part in sorted(parts, key=lambda x: int(re.search(r'part(\d+)', x).group(1))):
            with open(part, "rb") as infile:
                outfile.write(infile.read())
    return output_file

# ============================
# 设置窗口
# ============================

class SettingsWindow(tk.Toplevel):
    def __init__(self, master, config, callback):
        super().__init__(master)
        self.title("设置")
        self.config = config
        self.callback = callback  # 保存后回调更新主程序
        self.iconbitmap(resource_path("icon.ico"))
        self.setup_ui()

    def setup_ui(self):
        frame = tk.Frame(self)
        frame.pack(padx=10, pady=10)

        tk.Label(frame, text="默认保存目录：").grid(row=0, column=0, sticky="w")
        self.dir_entry = tk.Entry(frame, width=50)
        self.dir_entry.grid(row=0, column=1, padx=5)
        self.dir_entry.insert(0, self.config.get("default_save_dir", get_exe_dir()))
        tk.Button(frame, text="选择目录", command=self.browse_dir).grid(row=0, column=2, padx=5)

        tk.Button(frame, text="保存设置", command=self.save_settings).grid(row=1, column=1, pady=10)

    def browse_dir(self):
        dir_selected = filedialog.askdirectory(title="选择默认保存目录", initialdir=self.dir_entry.get())
        if dir_selected:
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, dir_selected)

    def save_settings(self):
        self.config["default_save_dir"] = self.dir_entry.get()
        save_config(self.config)
        messagebox.showinfo("设置", "设置保存成功！")
        self.callback()  # 回调更新主程序
        self.destroy()

# ============================
# 主程序 GUI 类
# ============================

class GalUploaderDownloaderApp:
    def auto_unzip_and_cleanup(self, zip_path, extract_to, parts):
        # 解压 zip 文件
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_to)
            self.log("解压完成")
        except Exception as e:
            messagebox.showerror("解压错误", str(e))
            return
        # 删除 zip 文件
        try:
            os.remove(zip_path)
            self.log("已删除合并后的 zip 文件")
        except:
            pass
        # 删除分卷文件
        for p in parts:
            try:
                os.remove(p)
                self.log(f"已删除分卷文件: {p}")
            except:
                pass

    def __init__(self, root):
        self.root = root
        self.root.title("我要玩旮旯给木")
        # 设置图标（确保 icon.ico 存放于 exe 同目录）
        try:
            self.root.iconbitmap(resource_path("icon.ico"))
        except Exception as e:
            print("图标加载失败：", e)
        self.mode = tk.StringVar(value="upload")  # 默认上传模式
        self.file_path = None

        self.setup_ui()

    def setup_ui(self):
        # 菜单区，可打开设置和历史记录窗口
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="设置", command=self.open_settings)
        settings_menu.add_command(label="历史记录", command=self.show_history)
        menubar.add_cascade(label="选项", menu=settings_menu)

        # 模式选择区
        mode_frame = tk.Frame(self.root)
        mode_frame.pack(padx=10, pady=5, anchor="w")
        tk.Radiobutton(mode_frame, text="上传", variable=self.mode, value="upload").pack(side="left")
        tk.Radiobutton(mode_frame, text="下载", variable=self.mode, value="download").pack(side="left")

        # 文件/文件夹选择按钮
        self.select_button = tk.Button(self.root, text="选择文件/文件夹", command=self.select_path)
        self.select_button.pack(pady=5)

        # 开始执行按钮
        self.start_button = tk.Button(self.root, text="开始执行", command=self.start_process)
        self.start_button.pack(pady=5)

        # 进度条
        self.progress = ttk.Progressbar(self.root, length=400)
        self.progress.pack(pady=5)

        # 日志显示
        self.log_text = tk.Text(self.root, height=10, width=80)
        self.log_text.pack(padx=10, pady=5)
        self.log("程序启动")

    def log(self, message):
        self.log_text.insert(tk.END, f"{datetime.datetime.now().strftime('%H:%M:%S')} {message}\n")
        self.log_text.see(tk.END)

    def update_progress(self, value):
        self.progress["value"] = value
        self.root.update_idletasks()

    def open_settings(self):
        SettingsWindow(self.root, config, self.on_settings_update)

    def on_settings_update(self):
        # 设置更新后可在此处处理需要更新的内容，例如更新默认保存目录
        self.log(f"默认保存目录更新为: {config['default_save_dir']}")

    def show_history(self):
        history = config.get("upload_history", [])
        if not history:
            messagebox.showinfo("历史记录", "暂无上传记录！")
            return
        history_win = tk.Toplevel(self.root)
        history_win.title("上传历史记录")
        history_win.iconbitmap(resource_path("icon.ico"))
        listbox = tk.Listbox(history_win, width=80)
        listbox.pack(padx=10, pady=10)
        for item in history:
            listbox.insert(tk.END, item)
        tk.Button(history_win, text="关闭", command=history_win.destroy).pack(pady=5)

    def select_path(self):
        if self.mode.get() == "upload":
            self.file_path = filedialog.askdirectory(title="选择游戏文件夹")
        else:
            self.file_path = filedialog.askopenfilename(title="选择上传生成的 JSON 文件", filetypes=[("JSON 文件", "*.json")])
        if self.file_path:
            self.log(f"选择路径: {self.file_path}")

    def start_process(self):
        if not self.file_path:
            messagebox.showwarning("提示", "请先选择文件或文件夹")
            return
        self.progress["value"] = 0
        threading.Thread(target=self.handle_process, daemon=True).start()

    def handle_process(self):
        if self.mode.get() == "upload":
            self.upload_process()
        else:
            self.download_process()

    def upload_process(self):
        self.log("开始上传流程...")
        parts = split_zip_folder(self.file_path)
        self.log(f"分卷完成，共 {len(parts)} 个文件")
        results = []
        for idx, part in enumerate(parts):
            self.log(f"上传第 {idx+1}/{len(parts)} 个分卷：{os.path.basename(part)}")
            result = upload_file(part, self.log, self.update_progress)
            if result:
                result["index"] = idx
                results.append(result)
        # 生成 JSON 文件，保存到默认目录（用户在设置中指定）
        base_name = os.path.basename(self.file_path)
        save_dir = config.get("default_save_dir", get_exe_dir())
        json_path = os.path.join(save_dir, f"{base_name}.json")
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({"game_title": base_name,
                           "upload_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                           "volumes": results}, f, ensure_ascii=False, indent=2)
            self.log(f"上传记录 JSON 已保存到: {json_path}")
            # 更新历史记录（保存已产生 JSON 文件路径）
            history = config.get("upload_history", [])
            history.append(json_path)
            config["upload_history"] = history
            save_config(config)
            messagebox.showinfo("完成", f"上传完成，共上传 {len(results)} 个分卷")
        except Exception as e:
            messagebox.showerror("保存 JSON 错误", str(e))
        # 删除 temp_zip 临时目录及所有内容
        try:
            shutil.rmtree(os.path.join(get_exe_dir(), "temp_zip"))
            self.log("已删除临时压缩文件")
        except Exception as e:
            self.log(f"临时文件删除失败: {e}")


    def download_process(self):
        self.log("开始下载流程...")
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("JSON 读取错误", str(e))
            return

        base = data.get("game_title", "game")
        save_dir = config.get("default_save_dir", get_exe_dir())

        # 不使用中文目录名
        target_dir = os.path.join(save_dir, base + "_unpacked")
        os.makedirs(target_dir, exist_ok=True)

        volumes = data.get("volumes", [])
        downloaded_parts = []
        for i, entry in enumerate(volumes):
            file_id = entry["path"]
            part_name = f"{entry['title']}_part{entry['index']}.zip"
            part_path = os.path.join(save_dir, part_name)
            self.log(f"下载 {i+1}/{len(volumes)}：{part_name}")
            download_file(file_id, part_path, self.update_progress)
            downloaded_parts.append(part_path)

        # 合并为 zip 文件
        merged_zip = os.path.join(save_dir, f"{base}_merged.zip")
        merge_files(downloaded_parts, merged_zip)
        self.log("已合并所有分卷")

        # 解压 & 清理
        self.auto_unzip_and_cleanup(merged_zip, target_dir, downloaded_parts)

        self.log(f"全部流程完成，文件已解压到：{target_dir}")
        messagebox.showinfo("完成", "下载并解压流程已完成！")


# ============================
# 主函数入口
# ============================
if __name__ == "__main__":
    root = tk.Tk()
    app = GalUploaderDownloaderApp(root)
    root.mainloop()
