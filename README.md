# 正佳广场店经营日报 - 部署包

每天自动从摩打后台拉取门店经营数据，生成三张卡片式日报长图，并可推送文字摘要到钉钉群。

## 包含内容

| 文件 | 作用 |
|---|---|
| `daily_report.py` | 主脚本：拉取数据 + 生成三张图（经营概览 / 赠菜与折扣 / 出品超时） |
| `moda_client.py` | 摩打后台 API 客户端（自动登录、token 复用） |
| `render_report.py` | 画图引擎（三张长图全部在此） |
| `order_split.py` / `channel_stats.py` | 堂食/外卖拆解、美团/饿了么/京东渠道明细 |
| `send_detail.py` / `discount_detail.py` | 赠菜明细、折扣明细（按桌台/折扣率归类） |
| `timeout_top.py` | 出品超时统计（下单→传菜 > 20 分钟，已剔除三文鱼粥/寿司包/豆乳芝士） |
| `push_dingtalk.py` | 钉钉群自定义机器人 Webhook 推送文字摘要 |
| `ding_push.py` | Webhook 底层（加签、发送） |
| `config.json` | **所有需要同事修改的东西都在这里** |

## 安装步骤（同事电脑）

1. **装 Python 3.10+**：https://www.python.org/downloads/ 安装时勾选 "Add Python to PATH"

2. **装依赖**：在本目录打开命令行，执行
   ```
   pip install -r requirements.txt
   ```

3. **改 config.json**：
   - `moda.account` / `moda.password`：摩打后台登录账号密码
   - `store.store_id`：门店在后台的 ID（正佳是 16，其他门店去后台商店列表里查）
   - `store.table_count`：门店实际桌数（影响翻台率计算）
   - `store.store_label`：日报标题里显示的门店名
   - `dingtalk_webhook`：要推送的钉钉群「自定义机器人」的 access_token 和加签 secret（不需要推送就保持 enabled 为 false 或留空）

4. **测试**：双击 `运行日报.bat`，看到「日期 … 营业额 …」和三张 saved 图片即成功

## 定时自动运行

双击 `安装定时任务.bat`（右键"以管理员身份运行"更稳），即注册每天 22:30 的 Windows 计划任务。
以后每天 22:30 自动拉当天数据、生成图片、推送到群，日志写在 `daily.log`。

想改时间：`schtasks /Change /TN "正佳日报-每日2230" /ST 08:30`

## 已知注意事项（踩过的坑，勿改）

1. `daily_report.py` 里"历史区间查询 + 目标日单日查询"的拆分**不能合并**——后台 storeBusinessPool 跨日查询会把当天流水算两倍
2. `food_order/index` 接口查当日必须用 `created_arr` 参数，`date_arr` 已失效
3. 超时计算用的是 `created_at`/`deliver_at` 时间戳自算，后台的 `use_time` 字段不可信
4. 订单类型枚举：1=堂食，2=小程序外卖，4=美团，5=京东，6=饿了么
5. 后台返回的 `table_num`（台位配置）偏大，翻台率用 config 里的 `table_count` 手工口径

## 关于图片推送到钉钉

钉钉**自定义机器人 Webhook 只支持文字/Markdown**，发不了本地图片文件。本包默认推文字摘要。
如果需要把三张长图也发进群，两种方案：
- 用企业内部应用（钉钉开放平台创建应用拿 appkey/appsecret，调 media upload + 机器人消息），需要管理员开应用权限
- 或让各门店负责人电脑装 WorkBuddy，用其钉钉连接器以个人身份发图（当前正佳店就是这么做的）

## 安全提醒

config.json 里有后台明文密码，**不要外传此包给无关人员**；建议定期改后台密码。
