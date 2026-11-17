/* Sparse lazy-tree rules. Checking a folder performs no filesystem requests. */
(function (root) {
    'use strict';
    function key(path) {
        const normalized = String(path).replace(/\\/g, '/').replace(/\/+$/, '') || '/';
        return /^[a-z]:/i.test(normalized) || normalized.startsWith('//') ? normalized.toLowerCase() : normalized;
    }
    function inside(child, parent) {
        return child === parent || child.startsWith(parent.endsWith('/') ? parent : parent + '/');
    }
    class FolderSelection {
        constructor() { this.rules = new Map(); }
        included(path) {
            const target = key(path);
            let winner = '', included = false;
            for (const [rule, value] of this.rules) {
                if (inside(target, rule) && rule.length > winner.length) {
                    winner = rule; included = value.included;
                }
            }
            return included;
        }
        set(path, included) {
            const target = key(path);
            for (const rule of Array.from(this.rules.keys())) {
                if (inside(rule, target)) this.rules.delete(rule);
            }
            if (this.included(path) !== included) {
                this.rules.set(target, {path, included});
            }
        }
        state(path) {
            const target = key(path), included = this.included(path);
            const mixed = Array.from(this.rules.entries()).some(([rule, value]) =>
                rule !== target && inside(rule, target) && value.included !== included);
            return {checked: included && !mixed, indeterminate: mixed};
        }
        payload() {
            const values = Array.from(this.rules.values()).sort((a,b) => key(a.path).localeCompare(key(b.path)));
            return {paths: values.filter(v => v.included).map(v => v.path),
                    excluded_paths: values.filter(v => !v.included).map(v => v.path)};
        }
    }
    if (typeof module !== 'undefined' && module.exports) module.exports = FolderSelection;
    else root.WingScribeFolderSelection = FolderSelection;
})(typeof window !== 'undefined' ? window : globalThis);
