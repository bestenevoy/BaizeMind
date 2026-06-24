# 前端设计方案

> 最后更新：2026-06-25

## 1. 设计理念

### 核心原则
- **信息密度优先**：企业知识库工具，信息呈现效率 > 视觉留白
- **层级分明**：通过颜色深浅、字体粗细、间距大小建立清晰的信息层级
- **沉浸式交互**：减少视觉噪音，让用户聚焦于内容和对话
- **微交互反馈**：所有可交互元素提供 hover / active / loading 状态反馈

### 视觉风格
- **现代简约**：去除多余边框，使用背景色差异区分区域
- **渐变点缀**：Header 品牌区域和关键 CTA 使用蓝色渐变
- **毛玻璃效果**：Header 和悬浮卡片使用 `backdrop-blur` 透明效果
- **圆角统一**：全局 `--radius: 0.625rem`（10px），卡片内元素 `0.375rem`（6px）

## 2. 色彩系统

### 主题色
| 变量 | 浅色模式 | 深色模式 | 用途 |
|------|----------|----------|------|
| `--background` | `0 0% 100%` | `222 47% 6%` | 页面背景 |
| `--card` | `0 0% 100%` | `222 47% 8%` | 卡片背景 |
| `--primary` | `221 83% 53%` | `217 91% 60%` | 主色（按钮、链接、高亮） |
| `--muted` | `210 40% 96%` | `217 33% 15%` | 次要背景 |
| `--border` | `214 32% 91%` | `217 33% 18%` | 边框 |
| `--destructive` | `0 84% 60%` | `0 63% 31%` | 错误/删除 |

### 语义色
| 色彩 | 浅色 | 深色 | 用途 |
|------|------|------|------|
| 成功绿 | `#22c55e` | `#4ade80` | 完成状态、通过阈值 |
| 警告橙 | `#f59e0b` | `#fbbf24` | 处理中、未通过阈值 |
| 信息蓝 | `#3b82f6` | `#60a5fa` | Dense 检索、信息提示 |
| 紫色 | `#8b5cf6` | `#a78bfa` | BM25 检索、图谱节点 |

### 渐变
```css
/* Header 品牌 */
--gradient-brand: linear-gradient(135deg, hsl(221 83% 53%), hsl(245 83% 60%));

/* 统计卡片图标背景 */
--gradient-stat-1: linear-gradient(135deg, #3b82f6, #6366f1);
--gradient-stat-2: linear-gradient(135deg, #8b5cf6, #ec4899);
--gradient-stat-3: linear-gradient(135deg, #06b6d4, #3b82f6);
--gradient-stat-4: linear-gradient(135deg, #10b981, #06b6d4);
```

## 3. 排版

### 字号
| 用途 | 大小 | 行高 | 示例 |
|------|------|------|------|
| 页面标题 | 1.125rem (18px) | 1.75rem | "智能问答" |
| 卡片标题 | 0.875rem (14px) | 1.25rem | "文件夹" |
| 正文 | 0.875rem (14px) | 1.5rem | 聊天消息 |
| 辅助文字 | 0.75rem (12px) | 1rem | 时间戳、状态 |
| 数据数字 | 0.875rem (14px) | 1.25rem | 统计数值，`tabular-nums` |

### 字重
- 标题：`font-semibold`（600）
- 正文：`font-normal`（400）
- 数据/代码：`font-mono` + `tabular-nums`

## 4. 布局规范

### 首页布局（三栏）
```
┌─────────────────────────────────────────────────────────┐
│ Header (h-14, sticky, backdrop-blur)                     │
├──────────┬──────────────────────────────────────────────┤
│          │                                              │
│  左栏     │              聊天区域                          │
│  (2/12)  │              (10/12)                          │
│          │                                              │
│ 文件夹    │  ┌──────────────────────────────────────┐   │
│ 标签     │  │  消息列表 (ScrollArea)                  │   │
│ 统计     │  │                                      │   │
│          │  └──────────────────────────────────────┘   │
│          │  ┌──────────────────────────────────────┐   │
│          │  │  输入框 + 发送按钮                      │   │
│          │  └──────────────────────────────────────┘   │
└──────────┴──────────────────────────────────────────────┘
```

### 间距
- 页面外边距：`px-4`（16px）
- 卡片间距：`gap-4`（16px）
- 卡片内边距：`p-4`（16px）
- 元素间距：`gap-2`（8px）或 `gap-3`（12px）

## 5. 组件样式

### 5.1 Header
- 高度 `h-14`（56px），`sticky top-0 z-50`
- 背景 `bg-background/80 backdrop-blur-md`
- 底部边框 `border-b`
- 品牌名使用渐变文字 `bg-clip-text text-transparent bg-gradient-to-r`
- 导航项：`rounded-lg`，active 态 `bg-primary/10 text-primary`
- 在线状态：圆点 + 文字，绿/红/灰三态

### 5.2 聊天面板
- 消息气泡：用户 `bg-primary text-primary-foreground`，AI `bg-muted`
- 圆角 `rounded-2xl`（比卡片更大，增加亲和力）
- 头像：`w-8 h-8 rounded-full`，用户蓝色背景，AI 灰色背景
- 引用标注 `[1]`：`text-primary font-semibold underline`，点击跳转
- 处理步骤：可折叠面板，`bg-muted/30 rounded-lg p-2`
- 检索上下文：可折叠，每条 chunk 显示 filename + score + text

### 5.3 统计面板
- 2×2 网格布局
- 每格：图标（带渐变背景圆形）+ 标签 + 数值
- 图标背景使用不同渐变色区分
- 数值使用 `font-semibold tabular-nums`

### 5.4 文件夹树
- 根节点：`FolderOpen` 图标，蓝色
- 子节点：`Folder` 图标，按深度变色
- 选中态：`bg-primary/10 text-primary font-medium`
- 文档节点：`FileText` 图标，选中时 `Check` 图标
- 计数徽章：`bg-muted/50 rounded-full text-[11px]`

### 5.5 检索调试面板
- 顶部阈值栏：`bg-muted/30 rounded p-2`，阈值可点击编辑
- Tab 切换：底部边框高亮 `border-primary`
- Dense 结果：绿色边框（通过阈值）/ 红色边框（未通过）
- RRF 结果：显示归一化分数 + 通过/未通过图标
- Rerank 结果：显示 rerank_score + 通过/未通过图标

## 6. 动画

### 6.1 过渡
```css
/* 通用过渡 */
transition-colors          /* 颜色变化 */
transition-all duration-300 /* 所有属性，300ms */
```

### 6.2 关键动画
- **消息出现**：`animate-in fade-in slide-in-from-bottom-2 duration-300`
- **加载旋转**：`animate-spin`（Loader2 图标）
- **状态脉冲**：`animate-pulse`（在线检测中）
- **进度条**：`transition-all` + width 变化

### 6.3 自定义滚动条
```css
/* 细滚动条 */
.scrollbar-thin::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.scrollbar-thin::-webkit-scrollbar-thumb {
  background: hsl(var(--muted-foreground) / 0.3);
  border-radius: 3px;
}
.scrollbar-thin::-webkit-scrollbar-track {
  background: transparent;
}
```

## 7. 响应式

| 断点 | 布局变化 |
|------|----------|
| `< 1024px` (lg) | 三栏变为单栏，左栏隐藏或折叠 |
| `< 768px` (md) | 导航栏图标-only，文字隐藏 |
| `< 640px` (sm) | 统计面板单列，卡片全宽 |

## 8. 实现清单

- [x] 全局 CSS：自定义滚动条、渐变变量、消息动画
- [x] Header：品牌渐变文字、导航间距优化
- [x] StatsPanel：渐变图标背景、卡片间距优化
- [x] ChatPanel：消息气泡圆角增大、空状态优化
- [x] ChatMessage：引用交互优化、上下文面板美化
- [x] FolderTree：深度色彩、计数徽章样式
- [x] TagFilter：Badge 交互反馈
- [x] SearchDebugPanel：阈值栏、Tab 样式、结果卡片
