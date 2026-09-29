# IP 查询 API 文档

## 1. 当前状态

本 API 返回统一 JSON，并同时提供 `authoritative` 便于程序直接读取、`confidence` 投票信息和 `sources` 来源明细。

当前实际接入并验证的来源是 `ipip.la`、`ping0.cc`、`ip.net.coffee`，不是 8 个候选网站的完整接入。百度、IPPure、pingip.cn、Whoer、CleanIP 尚未全部形成稳定适配器；缺少来源不会伪装成成功结果。

不需要 Chrome 或第三方 Python 包。API 服务端通过 HTTP 读取公开页面/JSON，并在本地解析、归一化。网站结构变化、限流或反爬都可能让单个来源失败。

## 2. 启动

需要 Python 3.10 或更高版本。

```bash
python3 ip/api.py
```

默认监听 `127.0.0.1:8080`。公开监听时必须设置长随机密钥：

```bash
export IP_LOOKUP_API_KEY='替换为长随机密钥'
python3 ip/api.py --host 0.0.0.0 --port 8080 --timeout 10
```

生产环境还应在反向代理或负载均衡器上启用 HTTPS、访问限流和日志管理。不要把 API key 写入仓库或公开日志。

## 3. 端点

### `GET /api/v1/ip`

查询 API 服务所在机器的公网出口 IP。它不是调用 API 的客户端 IP，也不会自动使用调用者的本地代理。

```bash
curl http://127.0.0.1:8080/api/v1/ip
```

### `GET /api/v1/ip?ip={address}`

查询指定 IPv4 或 IPv6 地址。当前 `ipip.la` 和 `ip.net.coffee` 参与任意目标地址查询；`ping0.cc` 仅查询服务端出口地址，因此在此模式标为 `skipped`。

```bash
curl 'http://127.0.0.1:8080/api/v1/ip?ip=1.1.1.1'
```

### `GET /health`

返回服务健康状态，不发起外部 IP 查询。该端点不要求 API key。

```bash
curl http://127.0.0.1:8080/health
```

## 4. 认证

如果设置了 `IP_LOOKUP_API_KEY`，`/api/v1/ip` 必须提供 Bearer token：

```bash
curl -H 'Authorization: Bearer 替换为长随机密钥' \
  'http://127.0.0.1:8080/api/v1/ip?ip=1.1.1.1'
```

未设置密钥时适用于本机开发，不建议将无认证服务公开到互联网。`/health` 保持公开，供服务健康探测使用。

## 5. 成功响应

HTTP `200`，`Content-Type: application/json; charset=utf-8`。以下值是结构示意，不保证是当前实时查询结果：

```json
{
  "schema_version": "1.0",
  "queried_at": "2026-09-29T18:00:00+00:00",
  "query_ip": "1.1.1.1",
  "authoritative": {
    "data": {
      "ip": "1.1.1.1",
      "geo": {
        "country_code": "AU",
        "country_name": "Australia",
        "region": "Queensland",
        "city": "South Brisbane"
      },
      "network": {
        "asn": "AS13335",
        "isp": "Cloudflare, Inc.",
        "type": "hosting"
      },
      "risk": {
        "is_datacenter": true,
        "is_residential": false,
        "is_vpn": false,
        "is_proxy": false,
        "is_tor": false,
        "scores": {
          "trust_score": 41,
          "abuser_score": ""
        }
      }
    },
    "field_provenance": {
      "ip": {
        "selected_from": ["ipip.la", "ip.net.coffee"],
        "agreement": "2/2",
        "ratio": 1.0,
        "confidence": "medium",
        "selection": "majority"
      },
      "geo.city": {
        "selected_from": ["ip.net.coffee"],
        "agreement": "1/2",
        "ratio": 0.5,
        "confidence": "low",
        "selection": "source_priority_tiebreak"
      },
      "risk.scores.trust_score": {
        "selected_from": ["ip.net.coffee"],
        "confidence": "source_only",
        "selection": "provider_value_not_cross_compared"
      }
    },
    "selection_policy": "per_field_majority_then_source_priority"
  },
  "ip": "1.1.1.1",
  "country_code": "AU",
  "country": "Australia",
  "region": "Queensland",
  "city": "South Brisbane",
  "asn": "AS13335",
  "isp": "Cloudflare, Inc.",
  "network_type": "hosting",
  "is_datacenter": true,
  "is_residential": false,
  "is_vpn": false,
  "is_proxy": false,
  "is_tor": false,
  "trust_score": 41,
  "abuser_score": "",
  "geo_source_count": 3,
  "confidence": {
    "ip": {
      "agreement": "2/2",
      "ratio": 1.0,
      "source_count": 2,
      "level": "medium",
      "sources": ["ipip.la", "ip.net.coffee"]
    }
  },
  "successful_source_count": 2,
  "sources": [
    {
      "name": "ipip.la",
      "status": "ok",
      "weight": 1,
      "ip": "1.1.1.1",
      "country_code": "AU",
      "country": null,
      "region": "Queensland",
      "city": "Brisbane",
      "asn": "AS13335",
      "isp": "Cloudflare, Inc.",
      "network_type": "hosting"
    },
    {
      "name": "ping0.cc",
      "status": "skipped",
      "reason": "Only reports the requester's IP"
    },
    {
      "name": "ip.net.coffee",
      "status": "ok",
      "weight": 1,
      "ip": "1.1.1.1",
      "country_code": "AU",
      "country": "Australia",
      "region": "Queensland",
      "city": "South Brisbane",
      "asn": "AS13335",
      "isp": "Cloudflare, Inc.",
      "network_type": "hosting",
      "is_datacenter": true,
      "is_residential": false,
      "is_vpn": false,
      "is_proxy": false,
      "is_tor": false,
      "trust_score": 41,
      "abuser_score": "",
      "geo_source_count": 3
    }
  ]
}
```

### Authoritative view

`authoritative.data` 是便于程序直接消费的归一化结果，按 IP、地理、网络和风险分组。字段在没有可用来源时保留为 `null`。原有顶层字段也继续返回，便于兼容旧调用方。

`authoritative.field_provenance` 只记录有值字段的最终依据：

- `selected_from`：支持最终值的来源。
- `agreement`：获胜值票数 / 报告该字段的有效来源数。未提供字段的来源不进入分母。
- `ratio`：获胜票数占有效票数比例。
- `confidence`：投票可信等级，或非投票评分的 `source_only`。
- `selection`：多数、来源优先级平票裁决、单来源，或来源自带评分未交叉比较。

“authoritative”指按本服务规则选出的规范值，不代表绝对真实或官方权威。特别是 IP 地理位置和 VPN/代理检测都可能因供应商数据而有误。

### 投票与优先级

每个字段独立比较，不对整份来源记录投票。当前来源权重都为 1。同票时按以下优先级选值：

1. `ip.net.coffee`
2. `ipip.la`
3. `ping0.cc`

可信等级规则：获胜值至少 3 票且占比不低于 0.67 为 `high`；至少 2 票为 `medium`；否则为 `low`。评分字段不会跨来源投票或平均，而会标成 `source_only`。

### 来源明细

`sources` 保存每家来源的状态和本服务提取/归一化出的字段，不是原始 HTML 页面存档：

- `ok`：获得可用响应；通常包含 `weight` 和该来源识别出的字段。
- `error`：请求或解析失败，附带 `error`。
- `skipped`：该查询模式不适用，附带 `reason`。

来源结果和字段名未来可能随网站页面变化；调用方应以 `schema_version` 和 `authoritative.data` 为主，不要硬依赖未知的来源扩展字段。

## 6. 错误响应

错误响应为 JSON，包含 `schema_version` 和稳定的 `error` 标识。

| HTTP 状态 | `error` | 含义 |
|---|---|---|
| 400 | `invalid_query` | 存在未知或重复查询参数 |
| 400 | `ip_must_not_be_empty` | `ip` 参数为空 |
| 400 | `invalid_ip` | IP 地址格式非法 |
| 401 | `unauthorized` | Bearer token 缺失或错误 |
| 404 | `not_found` | 路径不存在 |
| 502 | `no_ip_available` | 所有可用方式均未能识别 IP；响应仍包含来源状态 |

单个上游失败不会使整个请求报错；只要最终识别出 IP，API 返回 `200`，失败详情放在 `sources` 中。

## 7. 延迟与使用约定

上游请求当前按来源依次执行，每个来源最多等待 `--timeout` 秒，因此最坏等待时间大致是各个实际请求超时之和。生产部署应在代理层设置合理的总请求超时和访问速率限制。请遵守各来源网站的使用条款及访问限制；不要尝试绕过验证码或反爬限制。
