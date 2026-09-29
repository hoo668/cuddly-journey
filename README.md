# cuddly-journey

## IP 查询

无需安装 Chrome 或 Python 第三方依赖：

```bash
python3 ip/lookup.py
python3 ip/lookup.py --ip 1.1.1.1 --json
```

当前接入已验证可直接读取的 ping0.cc、ipip.la 和 Net.Coffee 数据。结果按 IP、国家/地区、城市、ASN、运营商和网络风险分别投票；同票时按 Net.Coffee、ipip.la、ping0.cc 的优先级选值。JSON 会保留每个来源的原始判定、字段一致比例和可信等级；单一来源会标为低可信，不会把 `1/1` 当成多源确认。

JSON 字段兼容性（只统计当前已接入并验证的 3 个来源）：

| 覆盖范围 | 共同字段 |
| --- | --- |
| 三个来源都提供 | `ip`、`country_code`、`asn`、`isp` |
| 任意 IP 查询的两个来源（ipip.la、Net.Coffee）都提供 | `ip`、`country_code`、`region`、`city`、`asn`、`isp`、`network_type` |
| 仅 Net.Coffee 有稳定结构化返回 | `is_datacenter`、`is_residential`、`is_vpn`、`is_proxy`、`is_tor`、`trust_score` |

`print(...)` 是给人看的终端摘要；统一机器接口是带 `schema_version` 的 JSON。未获得的字段也会保留并设为 `null`，各来源原始响应的归一化结果保存在 `sources` 中。这里的覆盖统计不代表尚未接入的其他候选站点。

### HTTP API

使用 Python 标准库启动本地 API，无需 Chrome 或额外依赖：

完整端点、认证、响应结构、可信度规则及错误码见 [API.md](API.md)。

```bash
python3 ip/api.py
```

接口：`GET /api/v1/ip` 查询 API 服务所在机器的公网出口；`GET /api/v1/ip?ip=1.1.1.1` 查询指定 IPv4/IPv6；`GET /health` 检查服务。返回体与 CLI `--json` 完全同一格式。默认只监听 `127.0.0.1:8080`。

公开监听时必须设置 `IP_LOOKUP_API_KEY`，客户端通过 `Authorization: Bearer <密钥>` 传入：

```bash
export IP_LOOKUP_API_KEY='替换为长随机密钥'
python3 ip/api.py --host 0.0.0.0 --port 8080
```

GitHub Actions 适合定时/手动运行任务和生成 artifact，不能常驻提供 API；要让其他程序持续调用，需要将此服务部署到 VPS 或支持常驻 Python Web 服务的平台，并配置 HTTPS 和密钥。

在 GitHub Actions 的 **IP lookup** 工作流可手动查询任意 IPv4/IPv6，也会每天运行一次。留空 IP 时查的是 GitHub runner 的公网出口，不是触发工作流的电脑或本地代理。结果会显示在 Actions 的运行摘要中，并作为 `ip-lookup-result` artifact 保留 14 天。

其他候选站点暂不参与投票：百度页面不是稳定的逐 IP 查询响应，Whoer 在本次探测中返回 403；其余站点只有在确认可稳定、合规地直接获取结果后再接入，避免动态页面或反爬结果产生假票。