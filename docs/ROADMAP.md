# mavplan Roadmap（V1.1+）

> 定位：**无人机培训教学场景的任务规划工具**（辅助个人/机构开展 CAAC 等执照培训中的
> 航线规划教学、模拟飞行与考核评估），同时保持通用任务规划器能力。
> 节奏：快速迭代——每攒一批可交付功能即发一个小版本（semver）。

## 现状盘点（v1.0.0，2026-09-08）

- 任务规划：Waypoint/Mission CRUD、lawnmower/orbit/polygon 自动航迹、起飞/降落自动插入
- 导入导出：MAVLink(mav)、KML、CSV；KML 导入 + 模板库
- 分析：飞行日志解析（CSV/JSON）、compare_to_plan（覆盖率/命中率/高度偏差）
- 仿真：能量估算（BatteryModel）、风扰（WindModel）、围栏检查、HTML 报告
- 链路：pymavlink 上传下载（可选依赖）；CLI 全覆盖；76 tests / 76% 行覆盖

**面向培训教学的缺口**：无可视化（教学演示难）、无任务格式互转（与 QGC/MP/考试软件
迁移不便）、无航点动作（DO_ 命令教学）、无禁飞区/安全预检（安全意识教学）、
无任务书/判分闭环（考核场景空白）、测绘计算（进阶课程空白）。

## 版本路线图

### v1.1 —— 互操作层：任务格式互转 + 航点动作（第一批）

目标：任务文件能在 mavplan ↔ 主流地面站/考试软件间无损流动，航点可携带动作。

1. **QGC `.plan` 导入/导出**（JSON，含 home 位置、mission items、geo-fence、rally points）
   - 只读文件协议，不引第三方依赖（手写 serializer）
2. **Mission Planner `.waypoints`（txt）导入/导出**
   - 支持 `QGC WPL 110` 头格式
3. **航点动作模型**：DO_JUMP / DO_CHANGE_SPEED / DO_SET_CAM_TRIGG_DIST /
   DO_SET_SERVO / DO_GRIPPER 等常用 DO_* 命令
   - Waypoint 扩展 `action` 字段 + CLI `waypoint action` 子命令 + MAVLink 导出映射
4. **动作插入助手**：`pattern insert-photo`（沿航线按距离/时间插拍照点）——测绘教学基础

验收：round-trip 测试（mavplan → .plan → mavplan 无损）；动作在 mav 导出中编码正确；
新格式均有 golden-file 测试。

### v1.2 —— 可视化：任务预览 + 模拟回放（教学演示核心）

目标：无 GUI 依赖的"地图感"可视化，教员可直接投屏讲解。

1. **HTML 任务预览页**：`mission preview out.html`
   - 单文件自包含（内联 Leaflet 国产化前先用 OpenStreetMap 瓦片 + 离线降级线框图），
     显示航点序号/高度剖面/航向箭头/自动生成的 lawnmower 覆盖带
2. **飞行回放**：`analyze replay flight.csv --plan plan.json --out replay.html`
   - 时间轴滑块 + 飞行轨迹 vs 计划航线对比 + 实时速度/高度仪表
3. **KML 增强**：航点图标化、航线宽度/颜色参数化（供 Google Earth 教学演示）

验收：离线可用（无网时退化为矢量线框图）；回放帧率可调；生成文件 < 2MB。

### v1.3 —— 教学套件：任务书 + 自动判分 + 成绩报告（培训杀手锏）

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

### v1.4 —— 安全与验证：预检 + 空域意识教学

1. **禁飞区模型**：圆/多边形（KML 导入已有 → 直接复用为 no-fly zones）
2. **任务预检**：`mission check`——转弯半径 vs 最小转弯、坡度、max 距离/高度、
   与禁飞区相交检测、电池余量（接 v0.6 能量估算）
3. **超视距意识教学**：`simulate lost-link`（链路丢失 → 自动返航逻辑演示）
4. 预检报告并入 v1.3 成绩报告

验收：预检输出结构化告警列表；禁飞区相交几何有单元测试（含边界相切）。

### v1.5 —— 测绘计算：课程化（进阶培训）

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
| v1.1 | 格式互转 + 动作 | +30~40 tests | 无新依赖 |
| v1.2 | 可视化（HTML 自包含） | +15~20 tests | 无（模板字符串） |
| v1.3 | 教学套件 | +25~35 tests | 无新依赖 |
| v1.4 | 安全预检 | +15~25 tests | 无新依赖 |
| v1.5 | 测绘计算 | +20~30 tests | 无新依赖 |

原则：**零运行时新依赖**（可视化用自包含 HTML/JS 模板）；每个小版本保持 100% 测试绿；
每个功能带 CLI 冒烟示例，方便投屏演示。

## 待办

- [ ] 推 GitHub（等待用户提供 PAT）
- [ ] v1.1 拆 issue/任务清单
