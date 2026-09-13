"""unlock_keyboard —— 把「唤醒并解锁平板」封装成一次按键。

这是一个**薄壳组件**：它不自带一行业余的蓝牙逻辑，全部转发给上游的
`espidf_ble_keyboard`（ESP32 BLE HID 键盘）。它只做三件事：

1. 按 `wake_*` / `password` 参数拼出上游的 action 字符串；
2. 在**编译期**校验平台规则 —— iOS 必须 `secure_connections`、
   Android 不该带 passkey、密码不能含 `|`；
3. 暴露成一个普通的 ESPHome `button` 实体。

**为什么值得做成组件，而不是几行 YAML substitution：**

* 未定义的 substitution **不会报错**，只会带着字面量进固件 —— `"${password}"`
  变成 15 个真实字符，被原样打进平板的密码框。校验通过、编译通过、烧进去
  也看不出来，只有解锁失败时才暴露。这里用 `cv.Optional` 从根上堵掉。
* YAML 没有条件分支，没法表达「iOS 才要 secure_connections、Android 不能要
  passkey」这条规则。Python 侧可以直接判。

**设计约束**：本组件所在的板子上 Flash 余量可能很紧（实测 AIBOX0 加蓝牙后
只剩 7.9%），所以这里刻意**只放一个几乎无状态的 C++ 类**，全部智能都在
编译期算完。
"""

import esphome.codegen as cg
from esphome.components import button

CODEOWNERS = ["@myml"]

# 上游组件必须先加载：我们不实现蓝牙，只往它上面挂按钮
DEPENDENCIES = ["espidf_ble_keyboard"]

unlock_keyboard_ns = cg.esphome_ns.namespace("unlock_keyboard")

UnlockKeyboardButton = unlock_keyboard_ns.class_(
    "UnlockKeyboardButton", button.Button, cg.Component
)
