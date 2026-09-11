# mavplan Roadmap（V1.1+）

> 定位：**无人机培训教学场景的任务规划工具**（辅助个人/机构开展 CAAC 等执照培训中的
> 航线规划教学、模拟飞行与考核评估），同时保持通用任务规划器能力。
> 节奏：快速迭代——每攒一批可交付功能即发一个小版本（semver）。

## 现状盘点（v1.7.0，2026-09-11）

- 任务规划：Waypoint/Mission CRUD、lawnmower/orbit/polygon 自动航迹、起飞/降落自动插入；home 位置持久化
- 导入导出：MAVLink(mav)、**QGC `.plan` JSON、QGC WPL 110/120（双向）**、KML、CSV；KML 导入 + 模板库；`mission import` 自动探测格式
- 航点动作：MAV_CMD 常量层（NAV_*/DO_*）、`Mission.add_action()`、`add_camera_trigger()`、CLI `waypoint action` / `mission camera`
- 分析：飞行日志解析（CSV/JSON）、compare_to_plan（覆盖率/命中率/高度偏差）
- 仿真：能量估算（BatteryModel）、风扰（WindModel）、围栏检查、HTML 报告
- 教学：任务书/判分/HTML 成绩报告、场景库、批改、**离线任务预览 + 班级汇总 HTML（v1.7）**
- 链路：pymavlink 上传下载（可选依赖）；CLI 全覆盖

**仍缺**：飞行回放（`analyze replay`）、GUI、PyPI 发布流水线。

## 版本路线图

### v1.1 —— 互操作层：任务格式互转 + 航点动作 ✅（2026-09-08 完成）

1. **QGC `.plan` 导入/导出** ✅（含 home、mission items、plannedHomePosition；geo-fence/rally 导出空结构）
2. **Mission Planner `.waypoints` 导入/导出** ✅（`QGC WPL 110/120` 均支持，HOME 项提取为 mission.home）
3. **航点动作模型** ✅（actions.py 常量 + 名映射、`Mission.add_action()`、CLI `waypoint action`、WPL/.plan 导出映射）
4. **动作插入助手** ✅（`mission camera --mode distance|time --value N` 插 DO_SET_CAM_TRIGG_DIST/INTERVAL）

验收达成：WPL/.plan round-trip 测试（坐标 ±1e-6 级）；动作在 WPL/.plan/MAVLink 中编码一致；138 tests 全绿。

### v1.2 —— 可视化：任务预览 + 模拟回放（教学演示核心）⬜ 部分完成（预览并入 v1.7）

目标：无 GUI 依赖的"地图感"可视化，教员可直接投屏讲解。

1. **HTML 任务预览页**：`mission preview out.html` ✅（v1.7.0，2026-09-11）
   - 单文件自包含内联 SVG（离线），显示航点序号/高度剖面/航向箭头/lawnmower 覆盖带/禁飞区
2. **飞行回放**：`analyze replay flight.csv --plan plan.json --out replay.html` ⬜
   - 时间轴滑块 + 飞行轨迹 vs 计划航线对比 + 实时速度/高度仪表
3. **KML 增强**：航点图标化、航线宽度/颜色参数化（供 Google Earth 教学演示）⬜

验收：离线可用（无网时退化为矢量线框图）；回放帧率可调；生成文件 < 2MB。

### v1.3 —— 教学套件：任务书 + 自动判分 + 成绩报告（培训杀手锏） ✅（2026-09-08 完成）

目标：把 CAAC 超视距驾驶员"航线规划实操考核"流程数字化。

1. **任务书模型**：TaskSpec（起降点、必过航点/区域、高度/速度窗口、时间限制、
   禁飞区列表）—— JSON 定义，CLI `task` 命令组
2. **判分引擎**（基于 compare_to_plan 扩展）：
   - 约束违反检测：进入禁飞区/未达必过点/高度速度越窗/超时/超距
   - 评分：分项扣分 + 总分（0-100）+ 评语（中文）
3. **题库/任务生成**：`task generate --seed N --difficulty easy|medium|hard`
   - 按难度随机化必过点/窗口参数，供教员批量出题
4. **成绩报告**：HTML 报告（学员名/任务书/轨迹对比图/扣分明细）

验收：示例任务书 gold 数据 + 判分结果快照测试；一份可演示的样例报告。

### v1.4 —— 安全与验证：预检 + 空域意识教学 ✅（2026-09-08 完成，194 tests）

1. **禁飞区模型**：圆/多边形（KML 导入已有 → 直接复用为 no-fly zones）
2. **任务预检**：`mission check`——转弯半径 vs 最小转弯、坡度、max 距离/高度、
   与禁飞区相交检测、电池余量（接 v0.6 能量估算）
3. **超视距意识教学**：`simulate lost-link`（链路丢失 → 自动返航逻辑演示）
4. 预检报告并入 v1.3 成绩报告

验收：预检输出结构化告警列表；禁飞区相交几何有单元测试（含边界相切）。

### v1.5 —— 测绘计算：课程化（进阶培训）✅（2026-09-08 完成，216 tests）

1. **相机模型**：传感器尺寸/焦距/像素 → FOV、GSD、单张覆盖
2. **重叠率计算**：按相机 FOV + 航高自动推 lane spacing / 拍照间距
   （lawnmower 增强：`--camera` 参数自动算行距）
3. **覆盖率验证**：模拟航点网格覆盖 → 输出理论覆盖率（接 v0.6 仿真）

验收：GSD/重叠率公式文档化 + 数值测试；与已知航测公式手算对照 ±1%。

### v2.0 —— 平台化（远期，视需求）

- Tkinter/Web 简易 GUI（任务编辑 + 地图 + 回放整合）
- pymavlink 飞行中实时监控/上传校验
- 任务/学员管理（多学员批量判分、成绩导出 CSV）
- 中文文档站 + PyPI 发布流水线（CI：pytest + build + twine）

## 版本节奏

| 版本 | 内容 | 预计测试增量 | 依赖风险 |
|------|------|--------------|----------|
| v1.1 ✅ | 格式互转 + 动作 | +62 tests（138 总） | 无新依赖 |
| v1.2 ⬜ | 可视化（HTML 自包含） | +15~20 tests | 无（模板字符串） |
| v1.3 ✅ | 教学套件 | +25~35 tests | 无新依赖 |
| v1.4 ✅ | 安全预检 | +15~25 tests | 无新依赖 |
| v1.5 ✅ | 测绘计算 | +20~30 tests | 无新依赖 |

原则：**零运行时新依赖**（可视化用自包含 HTML/JS 模板）；每个小版本保持 100% 测试绿；
每个功能带 CLI 冒烟示例，方便投屏演示。

## 待办

- 任务/学员管理（多学员批量判分、成绩导出 CSV）
