"use strict";

module.exports = function registerTgIftttNodes(RED) {
    const definitions = {
        "tg-workflow": { inputs: 0, outputs: 0 },
        "tg-trigger": { inputs: 0, outputs: 1 },
        "tg-send-message": { inputs: 1, outputs: 1 },
        "tg-wait-message": { inputs: 1, outputs: 1 },
        "tg-click-button": { inputs: 1, outputs: 1 },
        "tg-answer-callback": { inputs: 1, outputs: 1 },
        "tg-read-messages": { inputs: 1, outputs: 1 },
        "tg-set-variable": { inputs: 1, outputs: 1 },
        "tg-condition": { inputs: 1, outputs: 2 },
        "tg-delay": { inputs: 1, outputs: 1 },
        "tg-end": { inputs: 1, outputs: 0 }
    };

    function EditorOnlyNode(config) {
        RED.nodes.createNode(this, config);
        const node = this;
        node.on("input", function onInput(msg, send, done) {
            const error = new Error("tg-ifttt Node-RED is an editor only; import the flow into the Python runtime");
            node.status({ fill: "red", shape: "ring", text: "export to Python runtime" });
            node.error(error, msg);
            if (typeof done === "function") {
                done(error);
            }
        });
    }

    function EditorOnlySource(config) {
        RED.nodes.createNode(this, config);
        this.status({ fill: "blue", shape: "ring", text: "editor only" });
    }

    Object.keys(definitions).forEach((type) => {
        const definition = definitions[type];
        RED.nodes.registerType(type, definition.inputs === 0 ? EditorOnlySource : EditorOnlyNode);
    });
};
