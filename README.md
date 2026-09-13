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

### 固定模式：一块板伺候一台设备

```yaml
button:
  - platform: unlock_keyboard
    keyboard_id: kb            # 必填：上游 espidf_ble_keyboard 的 id
    name: "Unlock iPad"
    os: ios                    # android（默认）| ios
    password: !secret ipad_lock_pin   # 可选；不填 = 只唤醒
```

### 分发模式：一个按钮解锁「当前连着的设备」

一块板挂了多台设备（上游 `host_slots`）时，按下时读上游的 `active_host_slot()`，
挑当前那台对应的密码，所以 HA 里只需要**一个实体**：

```yaml
button:
  - platform: unlock_keyboard
    keyboard_id: kb
    name: "Unlock Current Tablet"
    profiles:
      - host_slot: 0
        os: ios
        password: !secret ipad_lock_pin
      - host_slot: 1
        os: android
        password: !secret tablet_lock_pin
```

每个 profile 可以有自己的 `os` / `password` / `press_enter`，与上游的槽位一一对应。
当前槽位没配 profile 时，按钮**只唤醒**（不会拿错密码去开锁）。

> 前提是槽位切换正确。用上游的 `switch_host:N` 按钮或 `switch_host` 服务切槽，
> 切换需要 1–3 秒 —— 自动化里请等 `binary_sensor`（`type: paired`）变 `on` 再按解锁。

### 选项

| 选项 | 默认 | 说明 |
|---|---|---|
| `keyboard_id` | **必填** | 上游 `espidf_ble_keyboard` 的 id |
| `profiles` | 无 | 槽位列表，每项 `host_slot` + `os`/`password`/`press_enter`。与顶层 `password` 互斥 |
| `os` | `android` | 决定 `press_enter` 的默认值，并触发平台规则校验 |
| `password` | 无 | 锁屏 PIN。**不填 = 只唤醒**。不能含 `\|` 或换行 |
| `host_slot` | 无 | 固定模式下说明本按钮对应哪个槽位，让平台规则按该槽位生效的参数判断 |
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

> 一块板子只有一个 BLE 身份。要同时伺候多台设备，用上游的
> `host_slots` 分槽（iOS 那个槽写 `passkey_mode: secure_connections`），
> 而不是指望两个蓝牙名字 —— 上游不支持多实例。

### ⚠️ 「一直卡在配对中」通常是槽位保护，不是兼容性问题

上游有**槽位保护**：一个槽位一旦 bond 给某台设备，**只有它能重新连**。别的设备
来配对会被「**闪一下"已配对"、然后立刻踢掉**」—— 在设备侧看起来就是一直卡在配对中。

诊断方法：看 `paired` 传感器（反复被踢 → 始终 `off`）和活动槽位号。
解法二选一：

* **给新设备一个空槽位**（推荐，不动已有配对）：`switch_host:<空槽>` 后再配对；
* **`forget_host:<槽>`** 清掉旧 bond，然后重新配对（旧设备需要重新配）。

配对时**务必先在对端设备的蓝牙设置里删掉旧条目** —— 残留的半成品 bond 会干扰。

---

## 内存代价（实测数据，不是估算）

在 ESP32-S3（`esp32-s3-devkitc-1`，esp-idf，ESPHome 2026.8.2）上实测，
配置里已经包含音频、麦克风、屏幕、语音助手：

| | 加蓝牙前 | 加蓝牙后 | 增量 |
|---|---|---|---|
| Flash | 972,687 / 1,835,008（53.0%） | 1,689,759 / 1,835,008（**92.1%**） | **+700 KB** |
| RAM（静态） | 106,659 / 341,760（31.2%） | 172,803 / 341,760（**50.6%**） | **+64.6 KB** |

**绝大部分开销来自 Bluedroid 协议栈本身，不是本组件。**

> **两个容易误判的点（都是实测纠正过的）：**
>
> 1. 那个 `92.1%` 是 **app 分区**的占用，不是整片 Flash。上面这块板实际是
>    **16 MB** Flash（`esptool flash_id` 实测）。所以那一刻真正紧的**不是 Flash**，
>    而是**内部 RAM** —— 顺带说明 `web_control`（约 73 KB）在 16 MB 板子上并不是
>    开不起，只是没必要。
> 2. **静态 RAM 百分比没有参考价值。** 上表 50.6% 只统计编译期确定的分配；
>    Bluedroid 的堆和任务栈是**运行时**才要的。而启动日志里那句
>    `空闲堆=8447672 字节` 是 **PSRAM** —— DMA 缓冲、WiFi/BT 缓冲**必须用内部
>    RAM，PSRAM 顶不上**。「总共还剩 8MB」和「内部 RAM 已经干了」可以同时成立。
>
> 把 BLE 键盘塞进一台已经在跑语音助手 + 音频 + 屏幕的 S3 上，实测的失败方式是：
> 蓝牙占满内部 RAM → 屏幕 SPI 的 DMA 缓冲每秒分配失败 → WiFi 关联超时 →
> 降级启动 SoftAP 时**空指针崩溃重启**（`ieee80211_hostap_attach`，
> `EXCVADDR: 0x2c`）。结论：**专用一块板跑键盘，别和音频/屏幕挤在一起。**

---

## Android 解锁：实测出一条四步流程

在 ESP32-C3 + Android 平板上实测出来的。**两个「看起来冗余、其实不能省」的步骤**，
和一个**会让设备静默变砖的硬约束**：

```
① 唤醒脉冲（纯 Shift，按住 50ms）   屏幕点亮，且不触发任何锁屏手势
② 回车                              把锁屏从「上滑解锁」推到密码输入层
③ 等 2.5 秒（用 ESPHome 的 delay，非阻塞）
④ 输密码 + 回车提交（仅 Android；iOS 位数够了会自己提交）
```

### 为什么必须先唤醒、再回车（两步都不能省）

Android 锁屏默认停在**「上滑解锁」**那一层，**密码输入框根本不存在**。

| 只做唤醒 | 只发回车（给睡眠中的屏幕） |
|---|---|
| 屏幕亮了，但停在「滑动进入」，后面打的数字**没有落点** | 回车被「叫醒屏幕」这个过程吃掉（锁屏上手电筒会晃一下），同样停在滑动层 |

必须先用一个**不产生字符、也不触发锁屏手势**的键（纯 Shift 脉冲）把屏幕叫醒，
随后那一下按键才真正被当作输入、把锁屏推进到密码层。

### ⚠️ 「推到密码层」用哪个键，**因系统而异**

这是最容易踩的一个坑：**同一个键在不同系统上效果不同**。

| 系统 | 能用哪个键推到密码层 |
|---|---|
| Android | `Enter`(0x28) / `Space`(0x2C) / `Menu`(0x65) 都可以 |
| **HarmonyOS（鸿蒙）** | **只有 `Space`(0x2C)** —— 按 `Enter` 没反应，屏幕亮着但一直停在锁屏层，密码没地方输 |
| iOS | 待验证 |

所以这个键**必须做成按槽位/按系统可配**（本仓库的示例配置用 substitution +
按 `active_host_slot()` 分支实现），不能硬编码成回车。

### ⚠️ 硬约束：action 串里的 `delay` 是**同步阻塞**的

`wake_delay` 之类的等待写在 action 字符串里，执行时**阻塞主循环**。单核芯片
（ESP32-C3）任务看门狗 5 秒，实测：

| 动作阻塞时长 | 结果 |
|---|---|
| ~2.8 s | 正常 |
| ~4.8 s | **Task WDT 重启** |

而重启会触发 ESP-IDF 的 **OTA 回滚** —— 症状极具迷惑性：**你改了配置、dashboard
也显示烧写成功，但设备永远在跑旧固件**（日志里 `OTA rollback detected!
Rolled back from partition 'app0'`）。

所以：**等待一律交给 ESPHome 调度器的 `delay:`（非阻塞）**，设备侧只发短脉冲。
本组件在 `wake_delay > 3000` 时会给出编译期警告。

### ⚠️ 回车不能和打字写在同一个 action 串里

上游把 `send_string` 改成了**非阻塞**（上游 issue #7）。所以：

```yaml
# ✗ 错的：回车会立刻执行，比密码早到 ~80ms -> 变成「先提交空密码」
action: "string:123456 | delay:200 | combo:0x00:0x28"
```

实测报文时间戳：回车在 `t=7.61`、密码第一位在 `t=7.69` —— **回车先到**。
症状是「密码少一位」这种假象（其实一位不少，是提交时机错了）。

正确做法：打字和提交**分两次动作**，中间留够打字时间（6 位 × 80ms ≈ 0.5s）。
本组件的 `press_enter: false` 就是为这个准备的。

### 为什么这么慢是没法避免的

实测总耗时 **约 4.7 秒**（0.8s 唤醒→回车，2.5s 密码框就绪，0.6s 打字，其余是执行开销）。
唯一可安全收窄的是那个 **2.5 秒**（密码框就绪余量）；0.8s 和 0.6s 都是硬需求。

---

## 一个可在 HA 编辑的 kWh 实体（以及为什么需要两个实体）

**HA 的能源仪表板只接受 `sensor`**，而且要求 `device_class: energy` +
`state_class: total_increasing`。**`number` 实体选不进去** —— 所以想让
「能在 HA 编辑」和「能接能源仪表板」同时成立，需要两个实体：

```yaml
number:
  - platform: template
    name: "电量输入 (kWh, 可编辑)"
    id: energy_kwh
    min_value: 0
    max_value: 1000000
    step: 0.001
    mode: box                 # 输入框（而非滑块）
    optimistic: true          # 由 HA 直接写
    restore_value: true       # 跨重启保持
    initial_value: 0
    on_value:                 # 编辑后立刻同步，不等 60s 轮询
      - sensor.template.publish:
          id: energy_kwh_sensor
          state: !lambda 'return x;'

sensor:
  - platform: template
    name: "累计电量 (energy)"
    id: energy_kwh_sensor
    unit_of_measurement: "kWh"
    device_class: energy
    state_class: total_increasing
    accuracy_decimals: 3
    update_interval: 60s
    lambda: 'return id(energy_kwh).state;'
```

### ⚠️ 坑：带前缀的单位会被换算，`initial_value` 会错 1000 倍

模板 number 一旦写 `unit_of_measurement: "kWh"`，ESPHome 会把它换算到基准单位，
于是 **`initial_value: 0` 显示出来是 `1000`**。更要命的是：

* 运行期由 HA 写入的值是 **1:1 透传**的（设 2.5 就读到 2.5），
* 所以**只有初始值错**，看起来像"以前存下来的残留值"，很难联想到单位换算。

**做法：让 `number` 不带单位**，单位只由那个 `sensor` 承担。
（也可以只用一个 `sensor` 加 `state_class: total_increasing` 让 HA 自己累计，
但那样就不能手改数值了。）

### 另一条前提：这块板测不到真实用电

板上没有电流计（5V 来自 USB 供电），所以上面这个数值**是你手工填或自动化写的，
不是实测值**。要真实计量得外接 INA219 / INA226 / PZEM 之类的传感器，
再把它接到 `battery_level:` 或作为 `energy` 传感器的来源。

---

## 用「下拉框」代替多个切槽按钮（含「关闭」）

比起 3 个 `switch_host` 按钮 + 1 个状态文本传感器，一个 `select` 更省实体：
它**同时**显示当前模式和切换模式。关键是用到上游两个 **public C++ 方法**
（文档里没提，是翻 `espidf_ble_keyboard.h` 找到的）：

| 方法 | 作用 |
|---|---|
| `slot_broadcasts(slot)` | 该槽位当前是否广播 |
| `set_slot_broadcast(slot, on)` | 设置广播；**对活动槽位置 false 会直接断开当前主机**（内部 `esp_ble_gatts_close`）并停广播 → 这就是「关闭」 |

```yaml
select:
  - platform: template
    name: "模式"
    options: ["关闭", "${mode_0}", "${mode_1}"]
    update_interval: 5s
    lambda: |-
      const uint8_t slot = id(kb)->active_host_slot();
      if (!id(kb)->slot_broadcasts(slot)) return std::string("关闭");
      switch (slot) { case 0: return std::string("${mode_0}"); }
      return std::string("关闭");
    set_action:
      - lambda: |-
          if (x == "关闭") {
            id(kb)->set_slot_broadcast(id(kb)->active_host_slot(), false);
          } else {
            int slot = (x == "${mode_0}") ? 0 : 1;
            id(kb)->set_slot_broadcast(slot, true);   // 可能之前被关过
            id(kb)->switch_host(slot);
          }
          id(mode_select).publish_state(x);           // 立刻反馈，不等下次轮询
```

几点实测确认过的行为：

* **不会闪回旧值**：`switch_host()` 是**同步**设置 `active_slot_` 并立刻发布传感器
  状态的，所以选完下拉框不会先跳回旧选项。
* **「关闭」会持久化**（写 NVS `bcast` 键）：关掉某个槽位后重启，它仍然不广播。
  重新选中该模式即可恢复（`set_slot_broadcast(slot, true)`）。
* 上游对「永不广播的槽位」有完整语义：切过去会断开当前主机、电台静默、
  哪里都显示 "No BLE" —— 这正是我们要的「关闭」。

> 命名提醒：ESPHome 会把非 ASCII 实体名按**字符数**转成下划线，
> 于是 `输入密码` 和 `重启键盘`（都是 4 字符）会**撞名报错**
> （`Both convert to ASCII ID: '____'`）。给中文名加个 ASCII 后缀
> （`输入密码 (type)`）既解决冲突也更易读。

---

## 密码留空 = 这台设备不需要密码（必须挡住后续输入）

**组件侧**：`password` 用**真值**判断，`password: ""` 与「不写」等价 ——
平台规则校验（iOS 必须 `secure_connections` 等）只对"真要输密码"的项生效；
单个 `profiles` 条目的密码为空是合法的（表示那台设备没有锁屏密码）。
只有 `wake: false` 且**所有** profile 都没密码，才是配置错误。

**但真正危险的在流程侧**：如果密码为空、流程却照旧发提交键，等于在锁屏上
**「提交一次空密码」** —— 会计入失败尝试，反复触发甚至把设备锁掉。
所以流程必须自己判断当前槽位有没有密码：

```yaml
      - if:
          condition:
            lambda: |-
              std::string pw;
              switch (id(kb)->active_host_slot()) {
                case 0: pw = "${ipad_lock_pin}"; break;
                case 1: pw = "${android_lock_pin}"; break;
              }
              return !pw.empty();
          then:
            - button.press: kb_type_password
            - delay: 600ms
            - espidf_ble_keyboard.run_action: ...   # 提交
          else:
            - logger.log: "密码为空，跳过输入与提交"
```

实测（把某个槽位的 PIN 置空）：报文只剩「唤醒 + 推到密码层」，
**没有数字、没有提交键**，日志打印跳过提示。这正是无密码设备想要的 ——
唤醒加推一下就可能直接解开了。

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

按钮就是普通的 `button` 实体，直接按即可。一块板挂多台设备时，
`profiles:` 那一个按钮解锁的就是「当前连着的那台」：

```yaml
- alias: "回家唤醒并解锁平板"
  triggers:
    - trigger: state
      entity_id: binary_sensor.front_door
      to: "on"
  actions:
    - action: button.press
      target:
        entity_id: button.aibox0_unlock_current_tablet
```

如果要指定解锁哪一台，先切槽位、**等连上**再按 —— 切槽需要 1–3 秒，
抢跑发的按键会全丢：

```yaml
    - action: button.press
      target: { entity_id: button.aibox0_kb_host_ipad }
    - wait_for_trigger:
        - trigger: state
          entity_id: binary_sensor.aibox0_keyboard_paired
          from: "off"
          to: "on"
      timeout: "00:00:20"
      continue_on_timeout: false
    - action: button.press
      target: { entity_id: button.aibox0_ipad_unlock }
```

上游还提供 `binary_sensor`（`type: paired`）和 `sensor`（`type: active_host`），
前者用来等连接、后者用来在自动化里判断当前在哪台设备上。

---

## 许可

MIT
