import {
  BracketsCurly,
  Broadcast,
  CheckCircle,
  CircleNotch,
  Code,
  GitBranch,
  ListDashes,
  PlugsConnected,
} from "@phosphor-icons/react";

export const clone = (value) => JSON.parse(JSON.stringify(value));

export const NODE_LIBRARY = [
  { type: "telegram.send_message", label: "发送消息", hint: "向目标会话发送文本", icon: Broadcast, tone: "mint" },
  { type: "telegram.wait_message", label: "等待消息", hint: "按发送者和文本筛选", icon: ListDashes, tone: "slate" },
  { type: "telegram.click_button", label: "点击按钮", hint: "Inline 坐标 / Reply 文本", icon: PlugsConnected, tone: "amber" },
  { type: "telegram.answer_callback", label: "回答回调", hint: "Bot API callback query", icon: CheckCircle, tone: "blue" },
  { type: "telegram.read_messages", label: "读取消息", hint: "获取最近消息快照", icon: Code, tone: "slate" },
  { type: "set_variable", label: "设置变量", hint: "写入安全表达式变量", icon: BracketsCurly, tone: "slate" },
  { type: "condition", label: "条件分支", hint: "安全表达式判断", icon: GitBranch, tone: "rose" },
  { type: "delay", label: "延迟", hint: "等待指定秒数", icon: CircleNotch, tone: "slate" },
  { type: "end", label: "结束", hint: "结束当前流程", icon: CheckCircle, tone: "mint" },
];

export const EMPTY_WORKFLOW = {
  version: 1,
  workflow: { id: "new-workflow", name: "未命名流程", enabled: true, account: "" },
  triggers: [{ type: "manual" }],
  nodes: [
    { id: "send_start", type: "telegram.send_message", config: { target: "@example_bot", text: "/start" } },
    { id: "click_action", type: "telegram.click_button", config: { target: "@example_bot", keyboard: "auto", match: { type: "regex", value: "按钮文本" } } },
    { id: "end", type: "end", config: {} },
  ],
  edges: [
    { from: "send_start", to: "click_action" },
    { from: "click_action", to: "end" },
  ],
};

export function libraryEntry(type) {
  return NODE_LIBRARY.find((entry) => entry.type === type) || NODE_LIBRARY[NODE_LIBRARY.length - 1];
}

export function defaultConfig(type) {
  if (type === "telegram.send_message") return { target: "@example_bot", text: "/start" };
  if (type === "telegram.wait_message") return { target: "@example_bot", sender: "", text_match: { type: "contains", value: "" }, limit: 20 };
  if (type === "telegram.click_button") return { target: "@example_bot", keyboard: "auto", match: { type: "regex", value: "按钮文本" } };
  if (type === "telegram.answer_callback") return { callback_id: "", text: "已处理" };
  if (type === "telegram.read_messages") return { target: "@example_bot", limit: 20 };
  if (type === "set_variable") return { name: "result", value: "" };
  if (type === "condition") return { expression: "variables.result == true" };
  if (type === "delay") return { seconds: 2 };
  return {};
}
