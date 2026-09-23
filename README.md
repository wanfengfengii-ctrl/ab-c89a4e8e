# 卫星固定优先级遥测总线 · 可调度性分析台

为非抢占遥测总线在上线前确定**全局最优固定优先级**的全栈综合台。
工程师可编辑或导入 2–18 条带唯一编号的消息，由后端真实业务 API 精确求解，
并查看最优顺序下每条消息的**阻塞值、RTA 迭代轨迹与超期判据**。

> 局部按周期（Rate Monotonic）或截止期（Deadline Monotonic）排序在抖动、
> 任意截止期与阻塞项并存时可能把可行消息集误判超期；本台对全部 n! 个
> 固定优先级顺序做精确寻优，而非使用启发式排序。

## 模型

每条消息含整数参数：传输时长 `C`、周期 `T`、相对截止期 `D`、释放抖动 `J`，满足

```
1 ≤ C ≤ D ≤ T ≤ 10^9,    0 ≤ J ≤ D − C
```

给定高优先级在前的顺序，消息 `i` 的阻塞 `B_i` 为所有**低优先级**消息 `C` 的
最大值（无则为 0），响应时间从

```
r(0) = J_i + C_i + B_i
r(k+1) = J_i + C_i + B_i + Σ_{h∈高优先级} ceil((r(k) + J_h) / T_h) · C_h
```

迭代，**在定点或首次严格大于 `D_i` 时停止**，终值记为 `R_i`。

在全部顺序中依次最小化：

1. 超期消息数（`R_i > D_i` 的条数）；
2. `Σ min(R_i, D_i+1)`（超期项截止在 D+1，避免无界响应时间淹没目标）；
3. 同分取编号序列（自高优先级向低优先级）字典序最小者。

## 精确算法（不是枚举 n!）

`R_i` 只取决于**高优先级消息集合**与**低优先级集合的最大 C**，与两集合内部
顺序无关。据此：

- 以"已放置在最低优先级的消息子集 S"做子集 DP，`O(n·2^n)` 状态/边（n=18 时
  262,144 状态），每条边把某条消息放在当前最低优先级，成本是该消息的
  `(是否超期, min(R_i, D_i+1))`；
- 每个 `(消息 i, 高优先级集合 H)` 的 RTA 结果记忆化，并以"去掉最低集合位"
  的严格子集从**下方**安全预热（从上方预热可能收敛到伪高不动点）；
- 自高优先级贪心回溯：每一步选择仍能位于最优路径上的字典序最小编号。

后端测试用 `itertools` 暴力枚举全排列对 40 组随机实例做了正确性对照。
n=18 常规实例亚秒级，极高利用率（U≈0.9）病态实例约 10 秒级。

## 前端交互保证

- 编辑任意输入（含导入、增删行、调整自定义顺序）立即**撤下旧结果**；
- 请求携带单调序号并可 `AbortController` 取消，**迟到响应不会覆盖新草稿**；
- 非法输入由 API 返回 HTTP 422，错误体带字段定位
  （如 `loc = ["body","messages",0,"J"]`），页面在对应行字段下标红提示；
- 支持 JSON 数组与 CSV/TSV（`编号 C T D [J]`，可带表头）导入。

## 目录结构

```
backend/          FastAPI（app/scheduler.py 为算法核心，无第三方依赖可单测）
  app/main.py        /api/health  /api/solve  /api/analyze
  tests/             pytest（含全排列暴力对照）
frontend/         React 18 + Vite，nginx 静态托管并反代 /api
scripts/api_smoke.py  纯标准库 API 冒烟（退出码报告结果）
verify/           一次性 verify 服务镜像（代码测试 + 构建检查 + API 冒烟）
docker-compose.yml
```

## 运行

```bash
cp .env.example .env        # 可选：调整宿主机端口与健康检查参数
docker compose up --build
# 前端  http://localhost:${FRONTEND_HOST_PORT:-8080}
# 后端  http://localhost:${BACKEND_HOST_PORT:-8000}（/api/health）
```

### 一次性 verify 服务

`verify` 服务等待 backend/frontend 健康检查通过后，依次运行后端代码测试、
前端生产构建检查、对在线栈的 API 冒烟，随后**自行退出并以退出码报告结果**：

```bash
docker compose run --rm verify
echo $?        # 0 = 全部通过；非 0 = 有阶段失败
```

### 本地开发（无 Docker）

```bash
# 后端
cd backend && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload

# 前端
cd frontend && npm install && npm run dev   # /api 代理到 :8000

# 测试 / 冒烟
pytest -q
python3 ../scripts/api_smoke.py http://127.0.0.1:8000
```

## 可配置项（.env）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BACKEND_HOST_PORT` | `8000` | 后端宿主机端口（容器内固定 8000） |
| `FRONTEND_HOST_PORT` | `8080` | 前端宿主机端口（容器内固定 80） |
| `HEALTHCHECK_INTERVAL` | `10s` | 两服务健康检查间隔 |
| `HEALTHCHECK_TIMEOUT` | `3s` | 健康检查超时 |
| `HEALTHCHECK_RETRIES` | `5` | 连续失败次数 |
| `HEALTHCHECK_START_PERIOD` | `5s` | 启动宽限 |
| `CORS_ORIGINS` | 前端地址 | 直连后端时允许的浏览器来源 |

## API 摘要

- `POST /api/solve` — body `{messages:[{id,C,T,D,J}]}`，返回最优 `order`、
  目标值、搜索统计与逐条 `results`（含 `blocking`、`blocking_from_id`、
  `trajectory`、`response_time`、`deadline_miss`、`criterion`）。
- `POST /api/analyze` — 额外带 `order`（编号排列），分析工程师给定顺序。
- 校验失败统一 `HTTP 422 {"detail":[{"loc":[...],"msg":...,"type":...}]}`。
