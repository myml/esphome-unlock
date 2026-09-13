#pragma once

#include "esphome/core/component.h"
#include "esphome/core/log.h"
#include "esphome/components/button/button.h"
#include "esphome/components/espidf_ble_keyboard/espidf_ble_keyboard.h"

namespace esphome {
namespace unlock_keyboard {

static const char *const TAG = "unlock_keyboard";

/// 一个按钮 = 一次「唤醒脉冲 + 可选地输密码 + 可选地回车」。
///
/// 两种工作模式：
///
/// * **固定模式**（只给 `password`/`os`）：action 字符串在**编译期**就拼好了，
///   按下时原样交给上游的 execute_action()。
/// * **按槽位分发**（给 `profiles:`）：编译期为每个槽位各拼一条 action，
///   按下时读上游的 active_host_slot()，用当前连接那台设备对应的那条。
///   这就是「一个按钮解锁当前设备」的实现方式。
///
/// 自身不持有任何蓝牙状态，也没有动态分配 —— 槽位表是编译期定长的。
/// Flash 余量紧的板子上，这一点很重要。
class UnlockKeyboardButton : public button::Button, public Component {
 public:
  void set_parent(espidf_ble_keyboard::EspidfBleKeyboard *parent) { this->parent_ = parent; }
  void set_action(const std::string &action) {
    this->action_ = action;
    this->has_action_ = true;
  }

  /// 为某个槽位登记一条 action（profiles 模式）
  void set_slot_action(uint8_t slot, const std::string &action) {
    if (slot >= MAX_SLOTS) return;
    this->slot_actions_[slot] = action;
    this->has_slot_action_[slot] = true;
  }

  /// 当前槽位没有登记 profile 时用的兜底 action（通常只唤醒）
  void set_fallback_action(const std::string &action) {
    this->fallback_action_ = action;
    this->has_fallback_action_ = true;
  }

  void press_action() override {
    if (this->parent_ == nullptr) return;

    // 固定模式：编译期就定死了一条 action
    if (this->has_action_) {
      this->parent_->execute_action(this->action_);
      return;
    }

    // profiles 模式：按当前连接的槽位选
    const uint8_t slot = this->parent_->active_host_slot();
    if (slot < MAX_SLOTS && this->has_slot_action_[slot]) {
      ESP_LOGD(TAG, "当前槽位 %u，用该槽位的解锁动作", (unsigned) slot);
      this->parent_->execute_action(this->slot_actions_[slot]);
      return;
    }

    if (this->has_fallback_action_) {
      ESP_LOGD(TAG, "当前槽位 %u 没有配 profile，走兜底动作", (unsigned) slot);
      this->parent_->execute_action(this->fallback_action_);
      return;
    }

    ESP_LOGW(TAG, "当前槽位 %u 没有配 profile，也没有兜底动作，什么都没做", (unsigned) slot);
  }

  // 必须晚于上游键盘初始化 —— 上游自用 -200.0f，这里保持一致
  float get_setup_priority() const override { return -200.0f; }

 protected:
  /// 上游 MAX_HOST_SLOTS（host_slots 上限 10）
  static const uint8_t MAX_SLOTS = 10;

  espidf_ble_keyboard::EspidfBleKeyboard *parent_{nullptr};

  std::string action_;
  bool has_action_{false};

  std::string slot_actions_[MAX_SLOTS];
  bool has_slot_action_[MAX_SLOTS]{};

  std::string fallback_action_;
  bool has_fallback_action_{false};
};

}  // namespace unlock_keyboard
}  // namespace esphome
