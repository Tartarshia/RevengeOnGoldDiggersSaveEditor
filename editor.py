from __future__ import annotations

import copy
import os
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from rogd_model import (
    PROJECT_DIR,
    EditorError,
    discover_save_paths,
    is_game_running,
    load_json,
    run_steam_helper,
    save_archive,
    save_setting,
    sha256_file,
    validate_archive,
    validate_setting,
)
from steam_schema import Achievement, load_achievements
from story_graph import (
    RELATIONSHIP_CHARACTERS,
    all_story_nodes,
    chapter_unlock_status,
    load_story_graphs,
    plan_chapter_unlock,
    plan_maximum_relationship_route,
    plan_relationship_gate_route,
    plan_story_unlock,
    relationship_fields,
    relationship_gate_nodes,
    relationship_requirement_status,
    story_route_score,
)


class Editor(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("情感反诈模拟器：存档与成就修改器")
        self.geometry("1120x720")
        self.minsize(920, 580)
        self.paths = None
        self.setting = {}
        self.archive = {}
        self.achievements: list[Achievement] = []
        self.achievement_status: dict[str, bool] = {}
        self.story_graphs = {}
        self.status_var = tk.StringVar(value="正在读取……")
        self.path_var = tk.StringVar()
        self.summary_var = tk.StringVar()
        self._build_ui()
        self.after(50, self.refresh_all)

    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=10)
        header.pack(fill="x")
        ttk.Label(header, text="存档目录：").grid(row=0, column=0, sticky="w")
        ttk.Entry(header, textvariable=self.path_var, state="readonly").grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(header, text="刷新", command=self.refresh_all).grid(row=0, column=2, padx=4)
        ttk.Button(header, text="打开备份目录", command=self.open_backups).grid(row=0, column=3, padx=4)
        ttk.Label(header, textvariable=self.summary_var).grid(row=1, column=0, columnspan=4, sticky="w", pady=(7, 0))
        header.columnconfigure(1, weight=1)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10)
        self.achievement_tab = ttk.Frame(notebook, padding=8)
        self.collect_tab = ttk.Frame(notebook, padding=8)
        self.route_tab = ttk.Frame(notebook, padding=8)
        self.relationship_tab = ttk.Frame(notebook, padding=8)
        self.log_tab = ttk.Frame(notebook, padding=8)
        notebook.add(self.achievement_tab, text="Steam 成就")
        notebook.add(self.collect_tab, text="档案 / 差分")
        notebook.add(self.route_tab, text="剧情路线")
        notebook.add(self.relationship_tab, text="隐藏数值 / 结局")
        notebook.add(self.log_tab, text="操作日志")
        self._build_achievement_tab()
        self._build_collect_tab()
        self._build_route_tab()
        self._build_relationship_tab()
        self._build_log_tab()

        status = ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w", padding=5)
        status.pack(fill="x", side="bottom")

    @staticmethod
    def _tree(parent, columns, headings, widths):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        for column, heading, width in zip(columns, headings, widths):
            tree.heading(column, text=heading)
            tree.column(column, width=width, minwidth=60, stretch=(column == columns[-1]))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return tree

    def _build_achievement_tab(self):
        ttk.Label(
            self.achievement_tab,
            text="每次只解锁选中的一项；会调用游戏自带 Steam 接口并立即复读。不会修改 Steam 缓存文件。",
        ).pack(anchor="w", pady=(0, 8))
        self.achievement_tree = self._tree(
            self.achievement_tab,
            ("status", "id", "name", "description"),
            ("状态", "ID", "名称", "达成条件"),
            (80, 70, 220, 620),
        )
        actions = ttk.Frame(self.achievement_tab)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="刷新 Steam 状态", command=self.refresh_achievements).pack(side="left")
        ttk.Button(actions, text="解锁选中成就", command=self.unlock_selected_achievement).pack(side="left", padx=8)

    def _build_collect_tab(self):
        ttk.Label(
            self.collect_tab,
            text="逐条修改 setting.save。写入会同时备份 archive.save 与 setting.save，并同步到 Steam Cloud。",
        ).pack(anchor="w", pady=(0, 8))
        self.collect_tree = self._tree(
            self.collect_tab,
            ("section", "id", "unlocked", "new"),
            ("类别", "条目 ID", "已解锁", "新内容标记"),
            (150, 220, 100, 120),
        )
        actions = ttk.Frame(self.collect_tab)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="解锁选中条目", command=self.unlock_selected_collectible).pack(side="left")
        ttk.Button(actions, text="设为已读", command=lambda: self.set_selected_new_flag(False)).pack(side="left", padx=8)
        ttk.Button(actions, text="设为新内容", command=lambda: self.set_selected_new_flag(True)).pack(side="left")

    def _build_route_tab(self):
        ttk.Label(
            self.route_tab,
            text="完整关系图来自本机游戏资源。每次只补选中节点所需的最短前置路径，并保留当前游玩位置。",
        ).pack(anchor="w", pady=(0, 8))
        self.route_tree = self._tree(
            self.route_tab,
            ("status", "chapter", "id", "label", "category"),
            ("状态", "章节", "节点", "名称", "类型"),
            (90, 70, 130, 430, 150),
        )
        actions = ttk.Frame(self.route_tab)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="解锁选中剧情节点", command=self.unlock_selected_story_node).pack(side="left")
        chapter_actions = ttk.Frame(self.route_tab)
        chapter_actions.pack(fill="x", pady=(6, 0))
        ttk.Label(chapter_actions, text="整章回收：").pack(side="left")
        for chapter in map(str, range(1, 8)):
            ttk.Button(
                chapter_actions,
                text=f"第 {chapter} 章 100%",
                command=lambda selected=chapter: self.unlock_chapter(selected),
            ).pack(side="left", padx=(0, 5))

    def _build_relationship_tab(self):
        mapping = (
            "角色对应：第1章 陈欣欣 yl；第2章 唐晓甜 xt；第3章 陈欣如 xr / 真爱 xrza；"
            "第4章 宋诗琪 sq（并记录何月盈 yy、陈欣欣真爱 xx 与两条分支标记）；"
            "第5章 何月盈 yy；第6章 潘梦娜 mn；第7章汇总判定 mn、xt、yy、sq、xx。"
        )
        ttk.Label(self.relationship_tab, text=mapping, wraplength=1040, justify="left").pack(
            anchor="w", pady=(0, 4)
        )
        ttk.Label(
            self.relationship_tab,
            text="每一行都是游戏资源里的真实门槛。应用后会重建满足该门槛的选择链；不会直接伪造数值，也不会改变当前游玩位置。",
            wraplength=1040,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        self.relationship_tree = self._tree(
            self.relationship_tab,
            ("status", "chapter", "character", "branch", "requirement", "current"),
            ("当前", "章节", "角色 / 数值", "结局或分支", "解锁规则", "当前路线复算"),
            (72, 58, 205, 155, 360, 180),
        )
        actions = ttk.Frame(self.relationship_tab)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(
            actions, text="应用选中结局 / 分支路线", command=self.apply_selected_relationship_gate
        ).pack(side="left")
        ttk.Button(actions, text="刷新数值", command=self.refresh_relationships).pack(side="left", padx=8)

    def _build_log_tab(self):
        self.log_text = tk.Text(self.log_tab, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True)

    def log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def refresh_all(self) -> None:
        try:
            self.paths = discover_save_paths()
            self.path_var.set(str(self.paths.remote_dir))
            self.setting = load_json(self.paths.setting)
            self.archive = load_json(self.paths.archive)
            validate_setting(self.setting)
            validate_archive(self.archive)
            self.achievements = load_achievements()
            self.story_graphs = load_story_graphs()
            self.refresh_collectibles()
            self.refresh_routes()
            self.refresh_relationships()
            self.refresh_achievements()
            running = "运行中" if is_game_running() else "已关闭"
            self.summary_var.set(
                f"游戏：{running}    剧情路线: {len(self.archive['nodeMap'])}/{len(all_story_nodes(self.story_graphs))} 节点    "
                f"角色档案: {len(self.setting['roleProfile'])}    恋情档案: {len(self.setting['loveDrama'])}"
            )
            self.status_var.set("读取完成")
            self.log(f"读取存档完成；setting SHA-256 {sha256_file(self.paths.setting)[:16]}…")
        except Exception as exc:
            self.status_var.set("读取失败")
            self.log(f"错误：{exc}")
            messagebox.showerror("读取失败", str(exc), parent=self)

    def refresh_achievements(self) -> None:
        if not self.achievements:
            return
        try:
            ids = [item.achievement_id for item in self.achievements]
            result = run_steam_helper("status", *ids)
            self.achievement_status = {key: bool(value) for key, value in result["status"].items()}
            self.achievement_tree.delete(*self.achievement_tree.get_children())
            for item in self.achievements:
                achieved = self.achievement_status.get(item.achievement_id, False)
                self.achievement_tree.insert(
                    "", "end", iid=item.achievement_id,
                    values=("已获得" if achieved else "未获得", item.achievement_id, item.name, item.description),
                    tags=("achieved" if achieved else "missing",),
                )
            self.achievement_tree.tag_configure("achieved", foreground="#277a35")
            count = sum(self.achievement_status.values())
            self.log(f"Steam 成就状态：{count}/{len(self.achievements)}")
        except Exception as exc:
            self.log(f"读取 Steam 成就失败：{exc}")
            messagebox.showerror("Steam 状态读取失败", str(exc), parent=self)

    def refresh_collectibles(self) -> None:
        self.collect_tree.delete(*self.collect_tree.get_children())
        labels = {"roleProfile": "角色档案", "loveDrama": "恋情档案"}
        for section in ("roleProfile", "loveDrama"):
            for item_id, record in self.setting[section].items():
                iid = f"{section}:{item_id}"
                self.collect_tree.insert(
                    "", "end", iid=iid,
                    values=(labels[section], item_id, "是" if record.get("unLock") else "否", "是" if record.get("newFlag") else "否"),
                )

    def refresh_routes(self) -> None:
        self.route_tree.delete(*self.route_tree.get_children())
        for chapter, node in all_story_nodes(self.story_graphs):
            node_id = node["id"]
            unlocked = node_id in self.archive["nodeMap"]
            self.route_tree.insert(
                "", "end", iid=node_id,
                values=(
                    "已回收" if unlocked else "未回收",
                    f"第 {chapter} 章",
                    node_id,
                    node.get("label", node_id),
                    node.get("category", ""),
                ),
                tags=("achieved" if unlocked else "missing",),
            )
        self.route_tree.tag_configure("achieved", foreground="#277a35")

    @staticmethod
    def _display_requirement(requirement: str) -> str:
        result = requirement.replace("&&", " 且 ").replace("||", " 或 ")
        for field, character in sorted(RELATIONSHIP_CHARACTERS.items(), key=lambda item: -len(item[0])):
            result = result.replace(f"r.{field}", f"{character}[{field}]")
        return result.replace("n.", "已回收节点 ")

    def refresh_relationships(self) -> None:
        if not self.story_graphs or not self.archive:
            return
        self.relationship_tree.delete(*self.relationship_tree.get_children())
        for chapter, node in relationship_gate_nodes(self.story_graphs):
            requirement = node.get("requirement") or ""
            fields = relationship_fields(requirement)
            values, satisfied = relationship_requirement_status(
                self.archive, self.story_graphs, node["id"]
            )
            has_route = node["id"] in self.archive["nodeMap"]
            characters = " / ".join(
                dict.fromkeys(f"{RELATIONSHIP_CHARACTERS.get(field, field)} [{field}]" for field in fields)
            )
            current = (
                "，".join(f"{field}={values[field]}" for field in fields)
                if has_route
                else "尚未建立该节点路线"
            )
            self.relationship_tree.insert(
                "",
                "end",
                iid=node["id"],
                values=(
                    "满足" if satisfied else ("未满足" if has_route else "未建立"),
                    f"第 {chapter} 章",
                    characters,
                    node.get("label", node["id"]),
                    self._display_requirement(requirement),
                    current or "—",
                ),
                tags=("achieved" if satisfied else "missing",),
            )
        self.relationship_tree.tag_configure("achieved", foreground="#277a35")

    def apply_selected_relationship_gate(self) -> None:
        selection = self.relationship_tree.selection()
        if not selection:
            messagebox.showinfo("请选择", "请先选择一个结局或分支门槛。", parent=self)
            return
        if is_game_running():
            messagebox.showerror("请关闭游戏", "请先完全关闭游戏，再修改隐藏数值路线。", parent=self)
            return
        target = selection[0]
        entry = next(
            ((chapter, node) for chapter, node in relationship_gate_nodes(self.story_graphs) if node["id"] == target),
            None,
        )
        if entry is None:
            messagebox.showerror("规则不存在", f"找不到门槛节点 {target}。", parent=self)
            return
        chapter, node = entry
        before, _ = relationship_requirement_status(self.archive, self.story_graphs, target)
        try:
            updated, path, planned = plan_relationship_gate_route(
                self.archive, self.story_graphs, target
            )
        except Exception as exc:
            messagebox.showerror("无法规划门槛路线", str(exc), parent=self)
            return
        before_text = "，".join(f"{key}={value}" for key, value in before.items()) or "无"
        planned_text = "，".join(f"{key}={value}" for key, value in planned.items())
        prompt = (
            f"应用第 {chapter} 章路线：{node.get('label', target)}？\n\n"
            f"游戏门槛：{self._display_requirement(node.get('requirement') or '')}\n"
            f"当前复算：{before_text}\n"
            f"计划复算：{planned_text}（选择链 {len(path)} 个节点）\n\n"
            "程序会先回收抵达本章所需的节点，再重建一条满足该门槛的真实选择链。"
            "当前游玩位置不变；写入前会备份并校验 Steam Cloud。"
        )
        if not messagebox.askyesno("确认结局路线", prompt, parent=self):
            return
        try:
            backup_dir, digest = save_archive(self.paths, updated)
            self.archive = load_json(self.paths.archive)
            validate_archive(self.archive)
            actual, satisfied = relationship_requirement_status(
                self.archive, self.story_graphs, target
            )
            if not satisfied:
                raise EditorError("写入复读后，所选结局门槛仍未满足。")
            self.refresh_routes()
            self.refresh_relationships()
            actual_text = "，".join(f"{key}={value}" for key, value in actual.items())
            self.log(
                f"第 {chapter} 章 {node.get('label', target)} 门槛路线写入完成：{actual_text}；"
                f"备份 {backup_dir.name}；SHA-256 {digest[:16]}…"
            )
            messagebox.showinfo(
                "结局路线写入完成",
                f"已复读确认：{actual_text}\n满足 {node.get('requirement')}。\n"
                f"备份：{backup_dir}\n\n请从对应节点的前一段进入游戏验证分支。",
                parent=self,
            )
        except Exception as exc:
            self.log(f"结局路线写入失败：{exc}")
            messagebox.showerror("结局路线写入失败", str(exc), parent=self)

    def selected_story_node(self):
        selection = self.route_tree.selection()
        if not selection:
            return None
        node_id = selection[0]
        return next(
            ((chapter, node) for chapter, node in all_story_nodes(self.story_graphs) if node["id"] == node_id),
            None,
        )

    def unlock_selected_story_node(self) -> None:
        selected = self.selected_story_node()
        if selected is None:
            messagebox.showinfo("请选择", "请先选择一个剧情节点。", parent=self)
            return
        chapter, node = selected
        node_id = node["id"]
        if node_id in self.archive["nodeMap"]:
            messagebox.showinfo("已经回收", f"{node_id} {node.get('label', '')} 已在存档中。", parent=self)
            return
        if is_game_running():
            messagebox.showerror("请关闭游戏", "请先完全关闭游戏，再修改剧情路线。", parent=self)
            return
        try:
            updated, added = plan_story_unlock(self.archive, self.story_graphs, node_id)
        except Exception as exc:
            messagebox.showerror("无法规划路线", str(exc), parent=self)
            return
        prompt = (
            f"解锁第 {chapter} 章节点？\n\n"
            f"{node_id}  {node.get('label', '')}\n"
            f"将补入 {len(added)} 个尚缺的前置/目标节点。\n\n"
            "当前游玩位置不会改变；写入前会备份两个存档并同步 Steam Cloud。"
        )
        if not messagebox.askyesno("确认单项路线解锁", prompt, parent=self):
            return
        try:
            backup_dir, digest = save_archive(self.paths, updated)
            self.archive = load_json(self.paths.archive)
            validate_archive(self.archive)
            self.refresh_routes()
            self.refresh_relationships()
            total = len(all_story_nodes(self.story_graphs))
            self.summary_var.set(
                f"剧情路线: {len(self.archive['nodeMap'])}/{total} 节点    "
                f"角色档案: {len(self.setting['roleProfile'])}    恋情档案: {len(self.setting['loveDrama'])}"
            )
            self.log(
                f"剧情节点 {node_id} 写入完成；补入 {len(added)} 个节点；"
                f"备份 {backup_dir.name}；SHA-256 {digest[:16]}…"
            )
            messagebox.showinfo(
                "写入完成",
                f"已复读验证，共补入 {len(added)} 个节点。\n备份：{backup_dir}\n\n"
                "请启动游戏确认路线图；这项操作不会自动授予 Steam 成就。",
                parent=self,
            )
        except Exception as exc:
            self.log(f"剧情路线写入失败：{exc}")
            messagebox.showerror("写入失败", str(exc), parent=self)

    def unlock_chapter(self, chapter: str) -> None:
        chapter_nodes = self.story_graphs[chapter]["nodes"]
        chapter_ids = {node["id"] for node in chapter_nodes}
        chapter_missing, unfinished = chapter_unlock_status(self.archive, self.story_graphs, chapter)
        if not chapter_missing and not unfinished:
            messagebox.showinfo("已经完成", f"第 {chapter} 章节点及播放历史已经完整。", parent=self)
            return
        if is_game_running():
            messagebox.showerror("请关闭游戏", "请先完全关闭游戏，再修改剧情路线。", parent=self)
            return
        try:
            updated, added = plan_chapter_unlock(self.archive, self.story_graphs, chapter)
        except Exception as exc:
            messagebox.showerror("无法规划整章路线", str(exc), parent=self)
            return
        prerequisite_count = max(0, len(added) - len(chapter_missing) - len(unfinished))
        prerequisite_text = (
            f"另补 {prerequisite_count} 个前章路径节点。\n" if prerequisite_count else ""
        )
        prompt = (
            f"将第 {chapter} 章回收至 100%？\n\n"
            f"本章共 {len(chapter_nodes)} 个节点，当前缺少 {len(chapter_missing)} 个。\n"
            f"另有 {len(unfinished)} 个节点缺少完整播放记录，将一并修复。\n"
            f"{prerequisite_text}总计新增或修复 {len(added)} 条节点记录。\n\n"
            "当前游玩位置和已有分支不会改变；只执行一次备份、写入和 Steam Cloud 校验。\n"
            "此操作不会自动授予 Steam 成就。"
        )
        if not messagebox.askyesno("确认整章回收", prompt, parent=self):
            return
        try:
            backup_dir, digest = save_archive(self.paths, updated)
            self.archive = load_json(self.paths.archive)
            validate_archive(self.archive)
            actual_missing, actual_unfinished = chapter_unlock_status(
                self.archive, self.story_graphs, chapter
            )
            if actual_missing or actual_unfinished:
                raise EditorError(
                    f"写入复读后，第 {chapter} 章仍缺 {len(actual_missing)} 个节点、"
                    f"{len(actual_unfinished)} 个完整播放记录。"
                )
            self.refresh_routes()
            self.refresh_relationships()
            total = len(all_story_nodes(self.story_graphs))
            self.summary_var.set(
                f"剧情路线: {len(self.archive['nodeMap'])}/{total} 节点    "
                f"角色档案: {len(self.setting['roleProfile'])}    恋情档案: {len(self.setting['loveDrama'])}"
            )
            self.log(
                f"第 {chapter} 章已回收至 100%；新增或修复 {len(added)} 条节点记录；"
                f"备份 {backup_dir.name}；SHA-256 {digest[:16]}…"
            )
            messagebox.showinfo(
                "整章写入完成",
                f"第 {chapter} 章已复读确认 100%，共新增或修复 {len(added)} 条节点记录。\n"
                f"备份：{backup_dir}\n\n请启动游戏检查路线图。",
                parent=self,
            )
        except Exception as exc:
            self.log(f"第 {chapter} 章整章写入失败：{exc}")
            messagebox.showerror("整章写入失败", str(exc), parent=self)

    def set_chapter_five_max_relationship(self) -> None:
        if is_game_running():
            messagebox.showerror("请关闭游戏", "请先完全关闭游戏，再修改隐藏路线数值。", parent=self)
            return
        target = "n1537b"
        before = story_route_score(self.archive, self.story_graphs["5"], target, "yy")
        try:
            updated, path, score = plan_maximum_relationship_route(
                self.archive, self.story_graphs, "5", "yy", target
            )
        except Exception as exc:
            messagebox.showerror("无法规划沉沦度路线", str(exc), parent=self)
            return
        prompt = (
            "设置第五章最高沉沦度路线？\n\n"
            f"当前关底路线复算值：{before}\n"
            f"新路线复算值：{score}（共 {len(path)} 个节点）\n\n"
            "这会改写第五章的当前选择链，使游戏从路线本身计算出沉沦度，"
            "但不会删除任何已解锁节点，也不会改变当前游玩位置。\n"
            "写入前会备份并进行 Steam Cloud 哈希复读。"
        )
        if not messagebox.askyesno("确认隐藏数值路线", prompt, parent=self):
            return
        try:
            backup_dir, digest = save_archive(self.paths, updated)
            self.archive = load_json(self.paths.archive)
            validate_archive(self.archive)
            actual = story_route_score(self.archive, self.story_graphs["5"], target, "yy")
            if actual != score:
                raise EditorError(f"写入复读后的沉沦度路线为 {actual}，预期 {score}。")
            self.refresh_routes()
            self.refresh_relationships()
            self.log(
                f"第五章沉沦度路线已从 {before} 调整为 {actual}；"
                f"备份 {backup_dir.name}；SHA-256 {digest[:16]}…"
            )
            messagebox.showinfo(
                "隐藏路线写入完成",
                f"第五章关底路线已复读确认：沉沦度 {actual}。\n"
                f"备份：{backup_dir}\n\n请启动游戏，从第五章后段节点进入验证结局。",
                parent=self,
            )
        except Exception as exc:
            self.log(f"第五章沉沦度路线写入失败：{exc}")
            messagebox.showerror("隐藏路线写入失败", str(exc), parent=self)

    def selected_achievement(self) -> Achievement | None:
        selection = self.achievement_tree.selection()
        if not selection:
            return None
        chosen = selection[0]
        return next((item for item in self.achievements if item.achievement_id == chosen), None)

    def unlock_selected_achievement(self) -> None:
        item = self.selected_achievement()
        if item is None:
            messagebox.showinfo("请选择", "请先选择一项成就。", parent=self)
            return
        if self.achievement_status.get(item.achievement_id):
            messagebox.showinfo("已经获得", f"{item.name} 已经获得。", parent=self)
            return
        if is_game_running():
            messagebox.showerror("请关闭游戏", "请先完全关闭游戏，再触发 Steam 成就。", parent=self)
            return
        prompt = f"只解锁这一项 Steam 成就？\n\n{item.achievement_id}  {item.name}\n{item.description}"
        if not messagebox.askyesno("确认单项解锁", prompt, parent=self):
            return
        try:
            result = run_steam_helper("unlock", item.achievement_id)
            if not result.get("after"):
                raise EditorError("Steam 没有确认成就已获得。")
            self.log(f"已解锁并复读确认：{item.achievement_id} {item.name}")
            self.refresh_achievements()
            messagebox.showinfo("完成", f"Steam 已确认：{item.name}", parent=self)
        except Exception as exc:
            self.log(f"成就解锁失败：{exc}")
            messagebox.showerror("解锁失败", str(exc), parent=self)

    def selected_collectible(self):
        selection = self.collect_tree.selection()
        if not selection:
            return None
        section, item_id = selection[0].split(":", 1)
        return section, item_id

    def mutate_collectible(self, *, unlock=None, new_flag=None) -> None:
        selected = self.selected_collectible()
        if selected is None:
            messagebox.showinfo("请选择", "请先选择一个档案条目。", parent=self)
            return
        section, item_id = selected
        updated = copy.deepcopy(self.setting)
        record = updated[section][item_id]
        if unlock is not None:
            record["unLock"] = bool(unlock)
        if new_flag is not None:
            record["newFlag"] = bool(new_flag)
        if not messagebox.askyesno(
            "确认写入",
            f"只修改条目 {item_id}？\n\n写入前会备份两个存档，并同步 Steam Cloud。",
            parent=self,
        ):
            return
        try:
            backup_dir, digest = save_setting(self.paths, updated)
            self.setting = load_json(self.paths.setting)
            validate_setting(self.setting)
            self.refresh_collectibles()
            self.log(f"条目 {item_id} 写入完成；备份 {backup_dir.name}；SHA-256 {digest[:16]}…")
            messagebox.showinfo("写入完成", f"已复读验证。\n备份：{backup_dir}", parent=self)
        except Exception as exc:
            self.log(f"档案写入失败：{exc}")
            messagebox.showerror("写入失败", str(exc), parent=self)

    def unlock_selected_collectible(self) -> None:
        self.mutate_collectible(unlock=True, new_flag=True)

    def set_selected_new_flag(self, value: bool) -> None:
        self.mutate_collectible(new_flag=value)

    def open_backups(self) -> None:
        path = PROJECT_DIR / "backups"
        path.mkdir(exist_ok=True)
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])


def verify_install() -> None:
    paths = discover_save_paths()
    setting = load_json(paths.setting)
    archive = load_json(paths.archive)
    validate_setting(setting)
    validate_archive(archive)
    graphs = load_story_graphs()
    if len(all_story_nodes(graphs)) != 632:
        raise EditorError("内嵌故事关系图节点数量异常。")
    achievements = load_achievements()
    result = run_steam_helper("status", achievements[0].achievement_id)
    if achievements[0].achievement_id not in result.get("status", {}):
        raise EditorError("Steam 成就状态复读失败。")


if __name__ == "__main__":
    if "--verify-install" in sys.argv:
        verify_install()
    else:
        Editor().mainloop()
