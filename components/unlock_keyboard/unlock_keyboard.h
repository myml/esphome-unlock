#pragma once

#include "esphome/core/component.h"
#include "esphome/components/button/button.h"
#include "esphome/components/espidf_ble_keyboard/espidf_ble_keyboard.h"

namespace esphome {
namespace unlock_keyboard {

/// 一个按钮 = 一次「唤醒脉冲 + 可选地输密码 + 可选地回车」。
///
/// 自身不持有任何蓝牙状态：action 字符串在**编译期**就由 Python 侧拼好了，
/// 按下时原样交给上游的 EspidfBleKeyboard::execute_action()。
/// 所以这个类没有动态分配、没有定时器，Flash/RAM 开销可以忽略。
class UnlockKeyboardButton : public button::Button, public Component {
 public:
  void set_parent(espidf_ble_keyboard::EspidfBleKeyboard *parent) { this->parent_ = parent; }
  void set_action(const std::string &action) { this->action_ = action; }

  void press_action() override {
    if (this->parent_ != nullptr)
      this->parent_->execute_action(this->action_);
  }

  // 必须晚于上游键盘初始化 —— 上游自用 -200.0f，这里保持一致
  float get_setup_priority() const override { return -200.0f; }

 protected:
  espidf_ble_keyboard::EspidfBleKeyboard *parent_{nullptr};
  std::string action_;
};

}  // namespace unlock_keyboard
}  // namespace esphome
