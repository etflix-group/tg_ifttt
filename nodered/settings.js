const path = require("path");
const bcrypt = require(path.join(__dirname, "node_modules", "bcryptjs"));

const username = process.env.TG_IFTTT_NODERED_USER || "admin";
const password = process.env.TG_IFTTT_NODERED_PASSWORD || process.env.TG_IFTTT_ADMIN_TOKEN;
const credentialSecret = process.env.TG_IFTTT_NODERED_CREDENTIAL_SECRET
    || process.env.TG_IFTTT_MASTER_KEY
    || process.env.TG_IFTTT_ADMIN_TOKEN;

if (!password) {
    throw new Error("TG_IFTTT_NODERED_PASSWORD or TG_IFTTT_ADMIN_TOKEN is required");
}

module.exports = {
    flowFile: "flows.json",
    flowFilePretty: true,
    nodesDir: [path.join(__dirname, "nodes")],
    uiPort: Number(process.env.PORT || 1880),
    httpAdminRoot: "/nodered",
    httpNodeRoot: false,
    credentialSecret,
    adminAuth: {
        type: "credentials",
        users: [{
            username,
            password: bcrypt.hashSync(password, 10),
            permissions: "*"
        }]
    },
    paletteCategories: ["tg-ifttt", "common", "function", "network", "sequence", "parser", "storage"],
    editorTheme: {
        page: { title: "tg-ifttt · Node-RED" },
        header: { title: "tg-ifttt · Node-RED" },
        projects: { enabled: false },
        palette: {
            catalogues: []
        }
    },
    externalModules: {
        modules: false,
        palette: { allowInstall: false }
    },
    logging: {
        console: { level: "info", metrics: false, audit: false }
    }
};
