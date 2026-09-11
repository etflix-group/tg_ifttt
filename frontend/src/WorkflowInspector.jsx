import { ArrowRight, CheckCircle, Crosshair, GitBranch, Trash, WarningCircle, X } from "@phosphor-icons/react";

import { DEFAULT_SCHEDULE, getScheduleTrigger, setScheduleTrigger, validateNodeConfig } from "./flowModel.js";
import { libraryEntry } from "./nodeLibrary.js";

export function Field({ label, hint, error, children }) {
  return <label className={`field ${error ? "has-field-error" : ""}`}><span className="field-label">{label}</span>{children}{error ? <span className="field-error">{error}</span> : hint ? <span className="field-hint">{hint}</span> : null}</label>;
}

export function TextInput({ value, onChange, placeholder, mono = false, invalid = false, type = "text", readOnly = false }) {
  return <input type={type} aria-invalid={invalid || undefined} className={mono ? "input mono" : "input"} value={value ?? ""} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} readOnly={readOnly} />;
}

function errorFor(errors, text) {
  return errors.find((error) => error === text);
}

function TargetField({ config, workflowTarget, targetError, onChange }) {
  const updateTarget = (value) => {
    const next = { ...config };
    if (value.trim()) next.target = value;
    else delete next.target;
    onChange(next);
  };
  const inherited = typeof workflowTarget === "string" ? workflowTarget.trim() : "";
  return <Field label="目标会话" error={targetError} hint={inherited ? `留空继承流程默认：${inherited}；填写可覆盖` : "建议在流程头部设置默认目标会话；也可为当前节点单独覆盖"}><TextInput value={config.target || ""} invalid={Boolean(targetError)} onChange={updateTarget} placeholder={inherited || "@bot 或 numeric peer"} mono /></Field>;
}

function localDateString() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function ScheduleSelect({ label, value, options, suffix, disabled, onChange }) {
  return <><select className="select schedule-select" aria-label={label} value={value} disabled={disabled} onChange={(event) => onChange(Number(event.target.value))}>{options.map((option) => <option key={option} value={option}>{option}</option>)}</select><span className="schedule-unit">{suffix}</span></>;
}

export function ScheduleConfig({ triggers, onChange }) {
  const trigger = getScheduleTrigger(triggers);
  const schedule = { ...DEFAULT_SCHEDULE, ...(trigger || {}) };
  const enabled = Boolean(trigger);
  const seconds = Number(schedule.second) || 0;
  const randomLimit = Math.max(0, 59 - seconds);
  const update = (key, value) => onChange(setScheduleTrigger(triggers, { ...schedule, [key]: value, anchor_date: schedule.anchor_date || localDateString() }));
  const toggle = (checked) => onChange(setScheduleTrigger(triggers, checked ? { ...schedule, anchor_date: schedule.anchor_date || localDateString() } : null));
  return <section className={`schedule-panel ${enabled ? "is-enabled" : ""}`} aria-labelledby="schedule-config-title">
    <div className="schedule-heading"><div><span className="eyebrow">TRIGGER / SCHEDULE</span><h2 id="schedule-config-title">定时执行</h2><p>每隔指定天数，在当天固定时间启动流程。</p></div><label className="schedule-toggle"><input type="checkbox" checked={enabled} onChange={(event) => toggle(event.target.checked)} /><span>启用定时执行</span></label></div>
    <div className={`schedule-builder ${enabled ? "" : "is-disabled"}`} aria-disabled={!enabled}><span className="schedule-prefix">每</span><ScheduleSelect label="间隔天数" value={schedule.interval_days} options={Array.from({ length: 365 }, (_, index) => index + 1)} suffix="天" disabled={!enabled} onChange={(value) => update("interval_days", value)} /><ScheduleSelect label="执行小时" value={schedule.hour} options={Array.from({ length: 24 }, (_, index) => index)} suffix="时" disabled={!enabled} onChange={(value) => update("hour", value)} /><ScheduleSelect label="执行分钟" value={schedule.minute} options={Array.from({ length: 60 }, (_, index) => index)} suffix="分" disabled={!enabled} onChange={(value) => update("minute", value)} /><ScheduleSelect label="执行秒数" value={schedule.second} options={Array.from({ length: 60 }, (_, index) => index)} suffix="秒执行" disabled={!enabled} onChange={(value) => update("second", value)} /></div>
    <label className={`schedule-random ${enabled && schedule.random_seconds ? "is-checked" : ""}`}><input type="checkbox" aria-label="随机种子" checked={Boolean(schedule.random_seconds)} disabled={!enabled} onChange={(event) => update("random_seconds", event.target.checked)} /><span><strong>随机种子</strong><small>在 {seconds} 秒基础上随机增加 0～{randomLimit} 秒，最终不超过 59 秒</small></span></label>
    <p className="schedule-note">{enabled ? "保存版本后生效；间隔天数从启用当天开始计算。" : "未启用定时执行，流程仍可手动运行。"}</p>
  </section>;
}

export function NodeInspector({ node, workflowTarget = "", onChange, onRename, onDelete }) {
  if (!node) return <div className="inspector-empty"><GitBranch size={25} /><p>选择节点或连线</p><span>双击节点编辑，点击连线编辑分支条件</span></div>;
  const config = node.data.config || {};
  const errors = validateNodeConfig(node, workflowTarget);
  const update = (key, value) => onChange({ ...config, [key]: value });
  const updateNested = (group, key, value) => onChange({ ...config, [group]: { ...(config[group] || {}), [key]: value } });
  const targetError = errorFor(errors, "目标会话不能为空");
  const updateRawConfig = (event) => {
    try { onChange(JSON.parse(event.target.value)); } catch { /* keep the last valid object while editing */ }
  };
  return (
    <div className="inspector-content">
      <div className="inspector-heading"><div><span className="eyebrow">NODE CONFIG</span><h2>{node.data.label || libraryEntry(node.data.nodeType).label}</h2></div><button type="button" className="icon-button danger" onClick={onDelete} title="删除节点" aria-label="删除节点"><Trash size={17} /></button></div>
      <Field label="功能块名称" hint="可全部删除后重新输入；不影响节点 ID 与连线"><TextInput value={node.data.label} onChange={onRename} /></Field>
      <Field label="节点 ID" hint="用于表达式引用和连线定位"><TextInput value={node.id} mono readOnly /></Field>
      <div className={`type-chip ${errors.length ? "invalid" : ""}`}><span className="status-dot" />{node.data.nodeType}{errors.length ? <span className="type-chip-error">{errors.length} 个问题</span> : null}</div>
      {errors.length ? <div className="inspector-validation" role="alert"><WarningCircle size={16} /><div>{errors.map((error) => <span key={error}>{error}</span>)}</div></div> : null}

      {node.data.nodeType === "telegram.send_message" ? <>
        <TargetField config={config} workflowTarget={workflowTarget} targetError={targetError} onChange={onChange} />
        <Field label="消息内容" error={errorFor(errors, "消息内容不能为空")}><textarea aria-invalid={Boolean(errorFor(errors, "消息内容不能为空")) || undefined} className="textarea" value={config.text ?? ""} onChange={(event) => update("text", event.target.value)} rows={4} placeholder="/start" /></Field>
      </> : null}

      {node.data.nodeType === "telegram.wait_message" ? <>
        <TargetField config={config} workflowTarget={workflowTarget} targetError={targetError} onChange={onChange} />
        <Field label="发送者筛选"><TextInput value={config.sender} onChange={(value) => update("sender", value)} placeholder="可选" mono /></Field>
        <Field label="消息匹配"><div className="inline-fields"><select className="select" value={config.text_match?.type || "contains"} onChange={(event) => updateNested("text_match", "type", event.target.value)}><option value="exact">完全匹配</option><option value="contains">包含</option><option value="regex">正则</option></select><TextInput value={config.text_match?.value} onChange={(value) => updateNested("text_match", "value", value)} placeholder="签到成功" /></div></Field>
        <Field label="读取条数" error={errorFor(errors, "读取条数必须是正整数")}><TextInput value={config.limit ?? 20} invalid={Boolean(errorFor(errors, "读取条数必须是正整数"))} onChange={(value) => update("limit", Number(value) || 1)} /></Field>
      </> : null}

      {node.data.nodeType === "telegram.click_button" ? <>
        <TargetField config={config} workflowTarget={workflowTarget} targetError={targetError} onChange={onChange} />
        <Field label="来源消息 ID" hint="留空时读取目标会话最近一条消息"><TextInput value={config.message ?? ""} onChange={(value) => update("message", value ? Number(value) : undefined)} mono /></Field>
        <Field label="键盘模式"><select className="select" value={config.keyboard || "auto"} onChange={(event) => update("keyboard", event.target.value)}><option value="auto">自动识别</option><option value="inline">Inline Keyboard</option><option value="reply">Reply Keyboard</option></select></Field>
        <Field label="按钮匹配" error={errorFor(errors, "按钮匹配值不能为空")}><div className="inline-fields"><select className="select" value={config.match?.type || "exact"} onChange={(event) => updateNested("match", "type", event.target.value)}><option value="exact">完全匹配</option><option value="contains">包含</option><option value="regex">正则</option><option value="callback_data">Callback data</option><option value="position">位置</option></select><TextInput value={typeof config.match?.value === "object" ? JSON.stringify(config.match.value) : config.match?.value} invalid={Boolean(errorFor(errors, "按钮匹配值不能为空"))} onChange={(value) => updateNested("match", "value", value)} placeholder="✅ 每日签到" mono /></div></Field>
        <Field label="多命中策略"><select className="select" value={config.match?.multiple || "fail"} onChange={(event) => updateNested("match", "multiple", event.target.value)}><option value="fail">失败并人工确认</option><option value="first">取第一项</option></select></Field>
      </> : null}

      {node.data.nodeType === "telegram.answer_callback" ? <>
        <Field label="Callback Query ID" hint="通常来自 telegram.event 触发器"><TextInput value={config.callback_id} onChange={(value) => update("callback_id", value)} mono placeholder="{{ trigger.event.callback_query.id }}" /></Field>
        <Field label="回答文本"><TextInput value={config.text} onChange={(value) => update("text", value)} placeholder="已处理" /></Field>
      </> : null}
      {node.data.nodeType === "telegram.read_messages" ? <>
        <TargetField config={config} workflowTarget={workflowTarget} targetError={targetError} onChange={onChange} />
        <Field label="读取条数" error={errorFor(errors, "读取条数必须是正整数")}><TextInput value={config.limit ?? 20} invalid={Boolean(errorFor(errors, "读取条数必须是正整数"))} onChange={(value) => update("limit", Number(value) || 1)} /></Field>
      </> : null}
      {node.data.nodeType === "set_variable" ? <>
        <Field label="变量名" error={errorFor(errors, "变量名必须是安全标识符")}><TextInput value={config.name} invalid={Boolean(errorFor(errors, "变量名必须是安全标识符"))} onChange={(value) => update("name", value)} mono /></Field>
        <Field label="静态值"><textarea className="textarea" value={typeof config.value === "string" ? config.value : JSON.stringify(config.value ?? "")} onChange={(event) => update("value", event.target.value)} rows={3} /></Field>
        <Field label="安全表达式" hint="设置后优先于静态值"><TextInput value={config.expression} onChange={(value) => update("expression", value)} placeholder="steps.wait.message.text" mono /></Field>
      </> : null}
      {node.data.nodeType === "condition" ? <Field label="安全表达式" error={errorFor(errors, "条件表达式不能为空")}><textarea aria-invalid={Boolean(errorFor(errors, "条件表达式不能为空")) || undefined} className="textarea mono" value={config.expression || ""} onChange={(event) => update("expression", event.target.value)} rows={4} placeholder="variables.points > 10" /></Field> : null}
      {node.data.nodeType === "delay" ? <Field label="等待秒数" error={errorFor(errors, "等待秒数必须是非负数")}><TextInput value={config.seconds ?? 0} invalid={Boolean(errorFor(errors, "等待秒数必须是非负数"))} onChange={(value) => update("seconds", Number(value) || 0)} /></Field> : null}
      {node.data.nodeType === "end" ? <div className="terminal-note"><CheckCircle size={18} />这个节点会将流程标记为成功。</div> : null}

      <details className="advanced-config"><summary>查看原始配置</summary><textarea className="textarea mono" value={JSON.stringify(config, null, 2)} onChange={updateRawConfig} rows={9} spellCheck="false" /></details>
    </div>
  );
}

export function EdgeInspector({ edge, nodes, onChange, onDelete }) {
  if (!edge) return null;
  const source = nodes.find((node) => node.id === edge.source);
  const target = nodes.find((node) => node.id === edge.target);
  const condition = edge.data?.condition ?? edge.label ?? "";
  return (
    <div className="inspector-content edge-inspector">
      <div className="inspector-heading"><div><span className="eyebrow">CONNECTION</span><h2>流程连线</h2></div><button type="button" className="icon-button danger" onClick={onDelete} title="删除连线" aria-label="删除连线"><Trash size={17} /></button></div>
      <div className="edge-route"><div><span>FROM</span><strong>{source?.data.label || edge.source}</strong></div><ArrowRight size={15} /><div><span>TO</span><strong>{target?.data.label || edge.target}</strong></div></div>
      <Field label="分支条件" hint="留空表示默认路径；条件节点可用多条连线表达分支"><textarea className="textarea mono" value={condition} onChange={(event) => onChange(event.target.value)} rows={5} placeholder="variables.points > 10" /></Field>
      <div className="edge-note"><Crosshair size={16} />连线端点可拖动重连，也可以按 Delete 删除。</div>
    </div>
  );
}

export function WorkflowInspector({ node, edge, nodes, workflowTarget = "", selectionCount = 0, onChange, onRename, onDelete, onEdgeChange, onClose }) {
  const content = edge ? <EdgeInspector edge={edge} nodes={nodes} onChange={onEdgeChange} onDelete={onDelete} /> : selectionCount > 1 ? <div className="inspector-empty"><GitBranch size={25} /><p>已选择 {selectionCount} 个节点</p><span>可以复制、移动或删除；单击一个节点查看配置。</span></div> : <NodeInspector node={node} workflowTarget={workflowTarget} onChange={onChange} onRename={onRename} onDelete={onDelete} />;
  return <aside id="workflow-inspector" className="inspector"><div className="panel-title"><span>{edge ? "连线检查器" : "节点检查器"}</span><span className="panel-kicker">INSPECT</span><button type="button" className="panel-close inspector-close" onClick={onClose} aria-label="关闭检查器"><X size={16} /></button></div>{content}</aside>;
}
