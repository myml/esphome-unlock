"""unlock_keyboard button 平台：一个按钮 = 一次解锁动作。

生成的 action 链长这样（[] 内为可选）：

    key_hold:0x02:0x00 | delay:150 | release
    [| delay:2000 | string:<password> [| delay:200 | combo:0x00:0x28]]

第一段是**纯修饰键脉冲**（默认左 Shift）：它不产生任何字符，但足以点亮
睡死的屏幕。这一步是必须的 —— 屏幕没亮时第一次按键会被系统吃掉，
如果拿密码第一位去当唤醒键，密码就会少一位、解锁必然失败。
"""

import logging

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import final_validate as fv
from esphome.components import button
from esphome.components.espidf_ble_keyboard import EspidfBleKeyboard
from esphome.const import CONF_ID

from . import UnlockKeyboardButton

_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = ["espidf_ble_keyboard"]

CONF_KEYBOARD_ID = "keyboard_id"
CONF_PASSWORD = "password"
CONF_OS = "os"
CONF_HOST_SLOT = "host_slot"
CONF_WAKE_MODIFIER = "wake_modifier"
CONF_WAKE_KEY = "wake_key"
CONF_WAKE_HOLD = "wake_hold"
CONF_WAKE_DELAY = "wake_delay"
CONF_KEY_DELAY = "key_delay"
CONF_PRESS_ENTER = "press_enter"

OS_ANDROID = "android"
OS_IOS = "ios"

# 左 Shift：合法的 HID 输入（能唤醒屏幕），但不产生字符
DEFAULT_WAKE_MODIFIER = 0x02
# 0x00 = 只按修饰键本身（上游明确支持 key_hold:0x01:0x00 这种写法）
DEFAULT_WAKE_KEY = 0x00
DEFAULT_WAKE_HOLD = 150
DEFAULT_WAKE_DELAY = 2000
DEFAULT_KEY_DELAY = 200

# USB HID Keyboard/Keypad usage 0x28 = Enter
HID_KEY_ENTER = 0x28

# 上游 EspidfBleKeyboard::MAX_ACTION_DEPTH —— action 链的步骤数上限
MAX_ACTION_STEPS = 8
# 上游对 actions 覆盖串的长度上限；这里给 button 的 action 也提个醒
WARN_ACTION_LENGTH = 255

# 平台规则：只有真会输密码的按钮才受这些约束
PASSKEY_MODE_SECURE_CONNECTIONS = "secure_connections"


def _validate_password(value):
    value = cv.string_strict(value)
    if "|" in value:
        raise cv.Invalid(
            "password 不能包含 '|' —— espidf_ble_keyboard 用 '|' 分隔 action 链的"
            "步骤边界，密码里的 '|' 会被当成一步的结束，后半截密码不会被打出去。"
        )
    if "\n" in value or "\r" in value:
        raise cv.Invalid("password 不能包含换行符")
    return value


def _build_action(config):
    """把配置拼成上游的 action 字符串（编译期完成，运行时不拼字符串）。"""
    parts = [
        f"key_hold:0x{config[CONF_WAKE_MODIFIER]:02X}:0x{config[CONF_WAKE_KEY]:02X}",
        f"delay:{config[CONF_WAKE_HOLD]}",
        "release",
    ]

    password = config.get(CONF_PASSWORD)
    if password:
        parts.append(f"delay:{config[CONF_WAKE_DELAY]}")
        parts.append(f"string:{password}")
        if config[CONF_PRESS_ENTER]:
            parts.append(f"delay:{config[CONF_KEY_DELAY]}")
            parts.append(f"combo:0x00:0x{HID_KEY_ENTER:02X}")

    return " | ".join(parts)


def _effective_security(upstream, host_slot):
    """算出这个按钮所在槽位**实际生效**的 (passkey, 是否安全连接)。

    上游的配对参数可以按槽位覆盖：`hosts:` 里的条目带 passkey 时，该槽位就用它的
    passkey 和 passkey_mode（不写 passkey 的条目不会覆盖任何东西 —— 上游只在
    `if CONF_PASSKEY in host` 时才调用 set_host_slot_passkey）。没被覆盖就继承全局。
    """
    passkey = upstream.get("passkey")
    sc = upstream.get("passkey_mode", "legacy") == PASSKEY_MODE_SECURE_CONNECTIONS

    if host_slot is not None:
        for entry in upstream.get("hosts") or ():
            if entry.get("slot") == host_slot:
                if "passkey" in entry:
                    passkey = entry["passkey"]
                    sc = (
                        entry.get("passkey_mode", "legacy")
                        == PASSKEY_MODE_SECURE_CONNECTIONS
                    )
                break
    return passkey, sc


def _final_validate(config):
    """平台规则校验：只在「这个按钮真的要输密码」时才有意义。

    没有密码时，按钮退化成纯唤醒 —— 唤醒键在任何平台上都是合法的，
    所以这时不该因为上游的 passkey 设置去报错。
    """
    if CONF_PASSWORD not in config:
        return config

    # 上游不是多实例组件（一块板一个 BLE 身份），所以这里最多一项
    upstream = fv.full_config.get().get("espidf_ble_keyboard")
    if isinstance(upstream, list):
        upstream = upstream[0] if upstream else {}
    if not isinstance(upstream, dict):
        return config

    os_name = config[CONF_OS]
    host_slot = config.get(CONF_HOST_SLOT)

    # host_slot 要落在 host_slots 范围内，否则上游根本不会为这个槽位配对
    host_slots = upstream.get("host_slots", 4)
    if host_slot is not None and host_slot >= host_slots:
        raise cv.Invalid(
            f"host_slot 是 {host_slot}，但上游 espidf_ble_keyboard 的 host_slots "
            f"只有 {host_slots}（合法范围 0–{host_slots - 1}）。",
            [CONF_HOST_SLOT],
        )

    passkey, secure_connections = _effective_security(upstream, host_slot)
    mode = "secure_connections" if secure_connections else "legacy"

    if os_name == OS_IOS and not secure_connections:
        hint = (
            f"第 {host_slot} 号槽位" if host_slot is not None else "全局"
        )
        raise cv.Invalid(
            f"os: ios 要求{ hint }的 passkey_mode 是 secure_connections，"
            f"当前生效的是 '{mode}'。legacy 配对在 iOS 上不工作 —— "
            "症状是配对失败，或者表面配对成功但按键完全没反应。"
            "（用 host_slots 时记得在该槽位的 hosts: 条目里写上 passkey，"
            "上游只在条目带 passkey 时才应用它的 passkey_mode。）",
            [CONF_OS],
        )

    if os_name == OS_ANDROID and passkey is not None:
        _LOGGER.warning(
            "os: android 生效的配对参数里有 passkey，但 Android 的 BLE HID "
            "不支持 passkey 配对，实际会退化成 Just Works（无认证）。"
            "建议删掉该槽位的 passkey；若同一块板还要伺候 iOS，请把 iOS "
            "单独放进另一个 host_slot 并只在那里设 passkey。"
        )

    return config


FINAL_VALIDATE_SCHEMA = cv.All(
    cv.Schema({}, extra=cv.ALLOW_EXTRA),
    _final_validate,
)

CONFIG_SCHEMA = (
    button.button_schema(UnlockKeyboardButton)
    .extend(
        {
            cv.Required(CONF_KEYBOARD_ID): cv.use_id(EspidfBleKeyboard),
            cv.Optional(CONF_OS, default=OS_ANDROID): cv.one_of(
                OS_ANDROID, OS_IOS, lower=True
            ),
            # 一台板子可以分槽伺候多台设备（上游 host_slots）。写了槽位号，
            # 平台规则校验就会按该槽位**实际生效**的配对参数来判断，而不是全局的。
            cv.Optional(CONF_HOST_SLOT): cv.int_range(min=0, max=9),
            # 不填 = 只唤醒，不输密码（例如设备本来就没锁屏密码）
            cv.Optional(CONF_PASSWORD): _validate_password,
            cv.Optional(CONF_WAKE_MODIFIER, default=DEFAULT_WAKE_MODIFIER): cv.hex_uint8_t,
            cv.Optional(CONF_WAKE_KEY, default=DEFAULT_WAKE_KEY): cv.hex_uint8_t,
            cv.Optional(CONF_WAKE_HOLD, default=DEFAULT_WAKE_HOLD): cv.int_range(
                min=10, max=2000
            ),
            cv.Optional(CONF_WAKE_DELAY, default=DEFAULT_WAKE_DELAY): cv.int_range(
                min=0, max=10000
            ),
            cv.Optional(CONF_KEY_DELAY, default=DEFAULT_KEY_DELAY): cv.int_range(
                min=0, max=10000
            ),
            # 不填 = 按 os 自动决定：Android 要回车，iOS 通常自动提交
            cv.Optional(CONF_PRESS_ENTER): cv.boolean,
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
)


async def to_code(config):
    var = await button.new_button(config)
    await cg.register_component(var, config)

    parent = await cg.get_variable(config[CONF_KEYBOARD_ID])
    cg.add(var.set_parent(parent))

    # press_enter 的自动默认值：iOS 的密码框在位数够了以后自己提交，
    # 再补一个回车可能触发别的行为，所以默认不发。
    if CONF_PRESS_ENTER in config:
        press_enter = config[CONF_PRESS_ENTER]
    else:
        press_enter = config[CONF_OS] != OS_IOS
    config[CONF_PRESS_ENTER] = press_enter

    action = _build_action(config)

    steps = len(action.split("|"))
    if steps > MAX_ACTION_STEPS:
        # 只会因为上游改了模板或这里加了步骤才会发生，提前炸掉比运行时静默截断好
        raise cv.Invalid(
            f"生成的 action 有 {steps} 步，超过 espidf_ble_keyboard 的 "
            f"MAX_ACTION_DEPTH({MAX_ACTION_STEPS})，最后几步会被丢弃。"
            f"生成结果: {action}"
        )
    if len(action) > WARN_ACTION_LENGTH:
        _LOGGER.warning(
            "生成的 action 长 %d 字符（超过上游对其余 action 串的 %d 上限）；"
            "密码很长时建议改用 host_slots/宏。生成结果: %s",
            len(action),
            WARN_ACTION_LENGTH,
            action,
        )

    _LOGGER.info("unlock_keyboard '%s' -> %s", config.get("name", "?"), action)
    cg.add(var.set_action(action))
