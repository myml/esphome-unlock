# esphome-unlock

把「**唤醒并解锁平板**」封装成 ESPHome 里的一个按钮。

一块 ESP32 在平板/手机眼里就是一个蓝牙键盘；按一下 HA 里的按钮，ESP32 先发一个
不会产生字符的**修饰键脉冲**点亮屏幕，停顿，把锁屏 PIN 打进去，再按情况回车。
Android 平板和 iPad 都支持。

本组件是**薄壳**：它不自带任何蓝牙实现，全部转发给上游的
[`markusg1234/ESPHome-espidf_ble_keyboard`](https://github.com/markusg1234/ESPHome-espidf_ble_keyboard)。
它只负责三件事：

1. 按参数拼出上游的 action 字符串（**编译期**完成，运行时不拼字符串）；
2. 在编译期校验平台规则；
3. 暴露成一个普通的 ESPHome `button` 实体。

---

## 为什么值得做成组件

**一、光靠 YAML substitution 会静默出错。** ESPHome 对未定义的 substitution
**只给一条 WARNING，配置仍然有效**，`${password}` 会以字面量进固件：

```yaml
# unlock_pin 忘了定义时
if (strlen("${unlock_pin}") > 0) { ... }   # 编译通过
```

结果是 `${unlock_pin}` 这 15 个字符被原样打进平板的密码框 —— 校验通过、编译通过、
烧进去也看不出来，只有解锁失败时才暴露。本组件用 `cv.Optional(CONF_PASSWORD)`
从根上堵掉：不填就是「只唤醒」，填了就是真密码。

**二、YAML 没有条件分支。** 「iOS 必须 `secure_connections`、Android 不能带
passkey」这条规则没法用 substitution 表达，本组件在 Python 侧直接判。

---

## 安装

本组件依赖上游组件，所以 **`external_components:` 里必须挂两个**：

```yaml
external_components:
  # 上游：真正的 BLE HID 键盘实现（必须）
  - source:
      type: git
      url: https://github.com/markusg1234/ESPHome-espidf_ble_keyboard
      ref: main
      path: components
    refresh: 0s
    components: [ espidf_ble_keyboard ]

  # 本仓库
  - source:
      type: git
      url: https://github.com/myml/esphome-unlock
      ref: main
    refresh: 0s
    components: [ unlock_keyboard ]
```

> `refresh: 0s` 是**开发期**的写法：`external_components` 默认一天才刷新一次，
> 不改这个的话你推的改动当天不会生效。稳定之后可以删掉，用默认值。

完整可用示例见 [`example/unlock-ipad.yaml`](example/unlock-ipad.yaml) 和
[`example/unlock-android.yaml`](example/unlock-android.yaml)。

---

## 配置

```yaml
button:
  - platform: unlock_keyboard
    keyboard_id: kb            # 必填：上游 espidf_ble_keyboard 的 id
    name: "Unlock iPad"
    os: ios                    # android（默认）| ios
    password: !secret ipad_lock_pin   # 可选；不填 = 只唤醒
```

| 选项 | 默认 | 说明 |
|---|---|---|
| `keyboard_id` | **必填** | 上游 `espidf_ble_keyboard` 的 id |
| `os` | `android` | 决定 `press_enter` 的默认值，并触发平台规则校验 |
| `password` | 无 | 锁屏 PIN。**不填 = 只唤醒**。不能含 `\|` 或换行 |
| `press_enter` | 按 `os` 自动 | 打完密码后是否补一个回车（Enter，HID `0x28`）。Android 默认 `true`，iOS 默认 `false` —— iOS 的密码框位数够了会自己提交 |
| `wake_modifier` | `0x02` | 唤醒脉冲用的修饰键。`0x02`=左 Shift、`0x01`=左 Ctrl、`0x04`=左 Alt |
| `wake_key` | `0x00` | 唤醒脉冲按的主键。`0x00` = 只按修饰键本身（上游明确支持这种写法） |
| `wake_hold` | `150` | 修饰键按住多久（ms） |
| `wake_delay` | `2000` | 唤醒脉冲之后、开始输密码之前等多久（ms）。**屏幕慢就往上加** |
| `key_delay` | `200` | 打完密码、按回车之前等多久（ms） |

### 生成出来的 action 长这样

```
key_hold:0x02:0x00 | delay:150 | release
  | delay:2000 | string:654321 | delay:200 | combo:0x00:0x28
```

共 7 步，在上游的 `MAX_ACTION_DEPTH`（8）以内。超了会在编译期报错而不是运行时静默截断。

### 为什么唤醒要先按一个「没用的键」

屏幕睡死时，**把屏幕唤醒的那一次按键通常不会落进输入框**。如果直接拿密码第一位
去当唤醒键，密码就会少一位、解锁必然失败。所以这里先用**纯修饰键脉冲**：
它是合法的 HID 输入（足以点亮屏幕），但**不产生任何字符**，绝不会污染密码框。

---

## 平台规则

| | Android 平板 | iPad |
|---|---|---|
| 上游 `passkey_mode` | `legacy`，且**不要设 `passkey`** | **必须** `secure_connections` |
| `press_enter` 默认 | `true` | `false` |
| 锁屏方式 | **必须 PIN / 密码**，图案锁收不到键盘 | PIN / 密码都行 |
| 开机 | 关掉「安全启动 / 开机需 PIN」，否则重启后首次解锁谁也进不去 | 无此问题 |
| 键盘布局 | 要与 `keyboard_layout`（默认 `us`）一致，否则 `#` 会打成 `\` | 一般不用管 |
| 省电 | 部分 ROM 深度睡眠会断 BLE，把系统蓝牙加进省电白名单 | 对 HID 连接比较宽容 |

Android 的 BLE HID **不支持 passkey 配对**，设了也会退化成 Just Works（无认证）。
本组件在 `os: android` 且上游设了 `passkey` 时给出警告；`os: ios` 而上游不是
`secure_connections` 时**直接编译失败** —— 因为那个组合在 iPad 上是必然失败的。

> 一块板子只有一个 BLE 身份。要同时伺候 Android 和 iPad，用上游的
> `host_slots` 分槽（iOS 那个槽写 `passkey_mode: secure_connections`），
> 而不是指望两个蓝牙名字 —— 上游不支持多实例。

---

## 内存代价（实测数据，不是估算）

在 ESP32-S3（`esp32-s3-devkitc-1`，esp-idf，ESPHome 2026.8.2）上实测，
配置里已经包含音频、麦克风、屏幕、语音助手：

| | 加蓝牙前 | 加蓝牙后 | 增量 |
|---|---|---|---|
| Flash | 972,687 / 1,835,008（53.0%） | 1,689,759 / 1,835,008（**92.1%**） | **+700 KB** |
| RAM（静态） | 106,659 / 341,760（31.2%） | 172,803 / 341,760（**50.6%**） | **+64.6 KB** |

**绝大部分开销来自 Bluedroid 协议栈本身，不是本组件。** 加完只剩 **142 KB** Flash
余量，所以：

* 上游的 `web_control: true` 会再加约 73 KB（gzip 后），**不建议**在余量紧的板子上开；
* `RAM` 那 64.6 KB 只是**静态**占用，Bluedroid 运行起来还要吃堆。如果配置里有
  按「空闲堆」动态分配缓冲的逻辑，那些缓冲会缩水。

---

## 坑

* **不要在同一条配置里加 `esp32_ble_tracker` / `bluetooth_proxy`。** ESP32 只有一个
  BLE 控制器，`esp32_ble` 的 `setup_priority` 是 `BLUETOOTH`，会先把它抢走，
  键盘组件的 init 随后全部静默失败 —— 编译过、启动过、日志无异常，两个功能一起废。
  上游 README 专门用 CAUTION 标了这件事。
* **关机状态唤不醒。** BLE 做不到，这跟电脑要 Wake-on-LAN 是同一个道理。
* **平板如果睡眠时连 BLE 也停了，就只能等它重连（1–3 秒）。** 这是唯一必须上机实测的
  点。绕开的办法是让它根本不休眠（iPad 用引导式访问，Android 用固定应用/展台模式）。
* **改了 HID 描述符就要重新配对。** 上游固件更新若动了描述符，平板侧要删掉设备重新配。
* **Android 首次配对可能要试不止一次**（刷新 BLE 缓存和 bond 状态）。

---

## Home Assistant 自动化

```yaml
- alias: "回家唤醒并解锁平板"
  triggers:
    - trigger: state
      entity_id: binary_sensor.front_door
      to: "on"
  actions:
    - action: button.press
      target:
        entity_id: button.unlock_ipad
```

上游还提供 `binary_sensor`（`type: paired`）和 `sensor`（`type: active_host`）。
如果需要「确认连上了再发密码」，用它们做条件；切槽位需要 1–3 秒，抢跑发的按键会全丢。

---

## 许可

MIT
