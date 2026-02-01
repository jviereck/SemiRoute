const { execSync } = require('child_process');

function getPortFromGitBranch() {
    const basePort = 8000;

    try {
        const branch = execSync('git rev-parse --abbrev-ref HEAD', {
            encoding: 'utf-8',
            stdio: ['pipe', 'pipe', 'pipe']
        }).trim();

        if (branch === 'main') {
            return basePort;
        }

        // Check for branch ending in -<letter>
        const match = branch.match(/-([a-z])$/i);
        if (match) {
            const suffix = match[1].toLowerCase();
            const offset = suffix.charCodeAt(0) - 'a'.charCodeAt(0) + 1;
            return basePort + offset;
        }
    } catch (err) {
        // Fall back to default port
    }

    return basePort;
}

const PORT = getPortFromGitBranch();
const SERVER_URL = `http://127.0.0.1:${PORT}`;

module.exports = {
    PORT,
    SERVER_URL,
};
