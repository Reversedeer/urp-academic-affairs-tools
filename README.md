# URP 综合教务管理系统工具

面向 `jws.qgxy.cn` 的异步命令行工具，当前提供：

- 登录及验证码识别
- 本学期课表查询与 Excel 导出
- 教学评估选择课程、显式确认、并发等待后提交
- 会话过期自动重登、幂等请求重试和清晰的异常提示

## 环境要求

- Python 3.10
- Poetry 2.x

## 安装

```powershell
poetry install
Copy-Item .env.example .env
```

在 `.env` 中填写 `URP_USERNAME` 和 `URP_PASSWORD`

## 运行

以下两种方式都受支持：

```powershell
poetry run python -m urp_academic_affairs_tools.main
poetry run python urp_academic_affairs_tools/main.py
```

安装项目后也可以直接运行：

```powershell
poetry run urp-tools
```

## 教学评估

进入教学评估后，程序会列出已评教和未评教课程。可输入单个序号、多个序号，或输入 `all` 提交全部未评教课程。

评教提交前仍需要输入确认语句。程序会并发打开选中课程的评教页面，统一等待 `URP_EVALUATION_WAIT_SECONDS` 秒后并发提交，避免每门课程都单独等待。

```powershell
URP_EVALUATION_WAIT_SECONDS=120
URP_EVALUATION_CONCURRENCY=3
```
