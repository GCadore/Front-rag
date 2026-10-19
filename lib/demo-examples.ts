// Exemplos de issues reais do testset (testes/testset_v3.jsonl), para a demonstração na tela de triagem.
// Gerado por script: título e corpo como o sistema recebe (referências do corpo mascaradas como [ref])
// e o gabarito (labels reais e itens relacionados) para comparar com o resultado.
// Todas foram criadas depois da data de corte (22/04/2026), então não estão no índice.

export interface DemoRelated {
  id: string;
  type: "issue" | "pr" | "doc";
  number: number | null;
  title: string;
  url: string;
}

export interface DemoExample {
  id: string;
  kind: "acerto" | "erro";
  note: string;
  url: string;
  title: string;
  body: string;
  expected: {
    labels: string[]; // labels que a triagem pode sugerir (type:, area:, integration:)
    otherLabels: string[]; // labels de processo (stale, needs:triage...), só para referência
    related: DemoRelated[];
  };
}

export const DEMO_EXAMPLES: DemoExample[] = [
  {
    "id": "#34070",
    "kind": "acerto",
    "note": "Acerta as labels e encontra issues relacionadas que estavam mascaradas no texto",
    "url": "https://github.com/backstage/backstage/issues/34070",
    "title": "Allow More Flexible Scaffolder Customization Using the New Frontend System",
    "body": "### 🔎 Search Terms\n\n```plain\n`scaffolder`, `customization`, `formFields`, `layouts`, `grouping`, `groups`, `software templates`, `NFS`\n```\n\n### 🗃️ Project Area\n\nSoftware Templates\n\n### 🔖 Need\n\nSome users of the **New Frontend System (NFS)** have reported limitations regarding customization.\n\nTo address these concerns, we need to provide a more flexible way of customizing the **Scaffolder** while leveraging the capabilities of NFS.\n\nRelated issues highlight the need for:\n\n- Customizing Template Groups ([ref], [ref])\n- Customizing the `TaskPageComponent` ([ref])\n- Providing a `formFields` prop ([ref])\n- Customization for `TemplateFilters` ([ref])\n- ...and many other potential use cases we may not yet have identified\n\n### 📝 Proposal\n\nMany of the described use cases are relatively straightforward to address.\nFor example, simply exporting certain components (e.g. from `plugins/scaffolder/src/alpha/components`) would already enable several customization scenarios.\n\nHowever, other cases require slightly more consideration. For instance, **Template Groups are currently static**.\nCustomizing them would require exposing them through an **API pattern similar to `formFields`**. This would allow `TemplateListContent` to consume these groups via props provided by the API.\n\nI propose a small refactoring of the **Scaffolder NFS** that:\n\n- Exports commonly used components relevant for customization\n- Exposes their associated props\n- Introduces a consistent API pattern for accessing configurable elements (similar to `formFields`)\n\nThis approach would allow components to access API-provided values (e.g. `formFields`) directly when needed.\n\nHowever, deeper customization would still require replacing entire components, which is not ideal.\nA better approach would be to control customization through props, passing API-provided values from the parent component instead.\n\nThis pattern is already used for `formFields` in `scaffolderTemplatesSubPage` within `extensions.tsx`.\n\n### Optional\n\nTo further align with **NFS patterns**, we could also consider providing Blueprints for each subroute within the Scaffolder.\n\n### Are you willing to submit a PR?\n\nYes, and I have enough information to get started",
    "expected": {
      "labels": [
        "type:suggestion",
        "area:scaffolder"
      ],
      "otherLabels": [
        "stale",
        "needs:triage"
      ],
      "related": [
        {
          "id": "doc-features/software-templates/configuration",
          "type": "doc",
          "number": null,
          "title": "features/software-templates/configuration",
          "url": "https://github.com/backstage/backstage/blob/e2fdc2b61fe9046574a8fc1d99b18053018db0a8/docs/features/software-templates/configuration.md"
        },
        {
          "id": "issue-32776",
          "type": "issue",
          "number": 32776,
          "title": "Expose grouping of software templates through New Frontend System",
          "url": "https://github.com/backstage/backstage/issues/32776"
        },
        {
          "id": "issue-33206",
          "type": "issue",
          "number": 33206,
          "title": "[NFS] Scaffolder missing property (TaskPageComponent)",
          "url": "https://github.com/backstage/backstage/issues/33206"
        },
        {
          "id": "issue-33439",
          "type": "issue",
          "number": 33439,
          "title": "Allow adding formFields prop when overriding ScaffolderPage",
          "url": "https://github.com/backstage/backstage/issues/33439"
        },
        {
          "id": "issue-33749",
          "type": "issue",
          "number": 33749,
          "title": "Bug: sub-page:scaffolder/templates extension should expose groups and templateFilter as factory params",
          "url": "https://github.com/backstage/backstage/issues/33749"
        }
      ]
    }
  },
  {
    "id": "#34395",
    "kind": "acerto",
    "note": "Acerta integration:gitlab e encontra a #28190, com a mesma causa raiz",
    "url": "https://github.com/backstage/backstage/issues/34395",
    "title": "Bug: `@backstage/integration@2.0.2` causes GitLab requests to fail with 406 Not Acceptable on self-hosted GitLab",
    "body": "### 🔎 Search Terms\n\n```plain\ngitlab integration, techdocs issue, 406, upgrade, v1.51.0\n```\n\n### 🗃️ Project Area\n\nTechDocs\n\n### 🔗 External Integration\n\nGitLab\n\n### 📝 Description & Context\n\n## Bug: `@backstage/integration@2.0.2` causes GitLab requests to fail with 406 Not Acceptable on self-hosted GitLab\n\n### Summary\n\nIn `@backstage/integration@2.0.2`, the `fetch` call inside `GitLabIntegration.createFetchStrategy()` had `mode: \"same-origin\"` removed. On Node 22, removing this option causes `undici` to set request headers (likely `Sec-Fetch-Mode: cors` and/or `Origin`) that some GitLab deployments — specifically self-hosted GitLab behind nginx — reject with **HTTP 406 Not Acceptable**.\n\nThis breaks TechDocs, `UrlReader.readTree`, and any other code path that goes through `GitLabIntegration.fetch`.\n\n### Affected versions\n\n- `@backstage/integration` **2.0.2** (broken)\n- `@backstage/integration` **2.0.1** (works)\n\nPulled in transitively by `@backstage/backend-defaults@0.17.1` (which bumped its `@backstage/integration` peer from `^2.0.1` to `^2.0.2`).\n\n### The change\n\nIn `dist/gitlab/GitLabIntegration.cjs.js`:\n\n```diff\n   createFetchStrategy() {\n-    let fetchFn = async (url, options) => {\n-      return fetch(url, { ...options, mode: \"same-origin\" });\n-    };\n+    let fetchFn = (url, options) => fetch(url, options);\n```\n\nThis is the only GitLab-relevant behavioral change between 2.0.1 and 2.0.2.\n\n### Reproduction\n\nSelf-hosted GitLab (any version recent enough to surface this; ours is behind nginx). Node 22.\n\n```js\n// verify-gitlab-fetch.mjs\nconst URL_TO_TEST = 'https://gitlab.example.com/api/v4/projects/group%2Frepo/repository/archive?sha=<branch>&path=<dir>';\nconst TOKEN = '<gitlab-token>';\n\nasync function hit(label, init) {\n  const res = await fetch(URL_TO_TEST, { ...init, headers: { Authorization: `Bearer ${TOKEN}` } });\n  console.log(label, '->', res.status, res.statusText);\n}\n\nawait hit('WITH    mode:\"same-origin\"', { mode: 'same-origin' });\nawait hit('WITHOUT mode',              {});\n```\n\nOutput against the exact same URL and token, back-to-back:\n\n```\nWITH    mode:\"same-origin\" -> 200 OK            (tar.gz body, 7282 bytes)\nWITHOUT mode               -> 406 Not Acceptable ({\"message\":\"406 Not Acceptable\"})\n```\n\nThe only difference between the two requests is the presence/absence of `mode: \"same-origin\"` in the `fetch` init.\n\n### Real-world symptom\n\nTechDocs build fails for every entity using a GitLab catalog source after upgrading `@backstage/backend-defaults` to `0.17.1` (which transitively resolves `@backstage/integration` to 2.0.2):\n\n```\nFailed to build the docs page for entity component:<name>: Failed to read tree (archive) from\nhttps://gitlab.example.com/<group>/<repo>/-/blob/<branch>/<path>/,\nhttps://gitlab.example.com/api/v4/projects/<group>%2F<repo>/repository/archive?sha=<branch>&path=<encoded-path>,\n406 Not Acceptable\n```\n\nStack: `GitlabUrlReader.readTree` → `DirectoryPreparer.prepare` → `DocsBuilder.build`.\n\n### Why removing `mode` matters in Node\n\nBrowser docs describe `mode` as a CORS-only property and imply Node ignores it. In practice, undici's `Request` constructor does parse `mode` and uses it to gate which `Sec-Fetch-*` / `Origin` headers are attached to the outgoing request. When `mode` is omitted, undici defaults to `\"cors\"` and adds headers (or sets header values) that the GitLab/nginx stack reads via content negotiation and rejects with 406.\n\nThe 2.0.2 change was presumably intended as a no-op cleanup (\"`mode` is browser-only\"), but it isn't a no-op on Node 22.\n\n### Suggested fix\n\nRestore `mode: \"same-origin\"` on the GitLab fetch call. It was load-bearing for self-hosted GitLab deployments, even though it looks vestigial.\n\n```js\nlet fetchFn = (url, options) => fetch(url, { ...options, mode: 'same-origin' });\n```\n\n### Workaround for users hitting this today\n\nPin `@backstage/integration` to `2.0.1` via root `package.json`:\n\n```json\n\"resolutions\": {\n  \"@backstage/integration\": \"2.0.1\"\n}\n```\n\n### Environment\n\n- Backstage 1.51.0\n- `@backstage/backend-defaults` 0.17.1\n- `@backstage/integration` 2.0.2\n- Node 22\n- Self-hosted GitLab behind nginx\n\n### 👍 Expected Behavior\n\n`GitLabIntegration.fetch()` — and everything that depends on it (`UrlReader.read`/`readTree`/`search`, `GitlabUrlReader`, TechDocs builds, the GitLab catalog provider, scaffolder GitLab actions) — should continue to succeed against self-hosted GitLab instances after upgrading `@backstage/integration` from 2.0.1 to 2.0.2. Removing `mode: \"same-origin\"` from the underlying `fetch` call was framed as a no-op cleanup, but it changes the outbound request headers undici emits on Node, so the upgrade should not silently start producing HTTP 406 Not Acceptable for previously working requests.\n\nConcretely, after upgrading:\n\n- TechDocs should build successfully for entities sourced from GitLab.\n- `GitlabUrlReader.readTree` should be able to fetch repository archives.\n- All GitLab API requests made through `GitLabIntegration.fetch` should produce the same status code and body they did on 2.0.1.\n\n### 📦 Reproduction Repo\n\n-\n\n### 🥾 Reproduction steps\n\n1. Run a self-hosted GitLab instance behind nginx (this is the configuration we've confirmed; it likely affects other reverse-proxy / WAF setups too). Have a project containing a TechDocs source directory on some branch (e.g. `backstage-integration`).\n\n2. Stand up a Backstage app (we're on 1.51.0, but the trigger is purely the integration version):\n   ```sh\n   npx @backstage/create-app\n   ```\n\n3. Configure a GitLab integration in `app-config.yaml` pointing at the self-hosted host, with a token that can read the project:\n   ```yaml\n   integrations:\n     gitlab:\n       - host: gitlab.example.com\n         token: ${GITLAB_TOKEN}\n   ```\n\n4. Add a catalog entity backed by that GitLab project with a TechDocs annotation (we use `backstage.io/techdocs-ref: url:.` on a `component:` entity registered from a `catalog-info.yml` inside the repo). Trigger a TechDocs build for it.\n\n5. Observe: with `@backstage/integration@2.0.1` resolved (the default with `@backstage/backend-defaults@0.17.0`), the build succeeds. With `@backstage/integration@2.0.2` resolved (pulled in transitively by `@backstage/backend-defaults@0.17.1`), the build fails:\n   ```\n   Failed to build the docs page for entity component:<name>:\n   Failed to read tree (archive) from\n   https://gitlab.example.com/<group>/<repo>/-/blob/<branch>/<path>/,\n   https://gitlab.example.com/api/v4/projects/<group>%2F<repo>/repository/archive?sha=<branch>&path=<encoded-path>,\n   406 Not Acceptable\n   ```\n\n6. To confirm the root cause is the removed `mode: \"same-origin\"` (independent of Backstage), hit the failing GitLab archive URL directly with Node 22's built-in `fetch`, varying only the `mode` option. Save as `verify-gitlab-fetch.mjs`:\n   ```js\n   const URL_TO_TEST = 'https://gitlab.example.com/api/v4/projects/<group>%2F<repo>/repository/archive?sha=<branch>&path=<encoded-path>';\n   const TOKEN = '<gitlab-token>';\n\n   async function hit(label, init) {\n     const res = await fetch(URL_TO_TEST, { ...init, headers: { Authorization: `Bearer ${TOKEN}` } });\n     console.log(label, '->', res.status, res.statusText);\n   }\n\n   await hit('WITH    mode:\"same-origin\"', { mode: 'same-origin' });\n   await hit('WITHOUT mode',              {});\n   ```\n   Run it:\n   ```sh\n   node verify-gitlab-fetch.mjs\n   ```\n   Observed output against the same URL and token, back-to-back:\n   ```\n   WITH    mode:\"same-origin\" -> 200 OK\n   WITHOUT mode               -> 406 Not Acceptable\n   ```\n   The only difference between the two requests is the presence/absence of `mode: \"same-origin\"` in the `fetch` init — i.e. exactly the line that was removed in `@backstage/integration@2.0.2`.\n\n7. Workaround that confirms the diagnosis in a real Backstage app: pin `@backstage/integration` back to 2.0.1 via root `package.json`:\n   ```json\n   \"resolutions\": {\n     \"@backstage/integration\": \"2.0.1\"\n   }\n   ```\n   Re-run TechDocs; the build succeeds again.",
    "expected": {
      "labels": [
        "type:bug",
        "area:techdocs",
        "integration:gitlab"
      ],
      "otherLabels": [
        "needs:triage"
      ],
      "related": [
        {
          "id": "issue-28190",
          "type": "issue",
          "number": 28190,
          "title": "🐛 Bug Report: GitlabUrlReader not working since undici change",
          "url": "https://github.com/backstage/backstage/issues/28190"
        }
      ]
    }
  },
  {
    "id": "#34022",
    "kind": "erro",
    "note": "Escolhe area:openapi-tooling, mas os mantenedores usaram area:catalog",
    "url": "https://github.com/backstage/backstage/issues/34022",
    "title": "🪲Swagger UI deep linking not working",
    "body": "### 🔎 Search Terms\n\n```plain\nswagger \"deep linking\"\n```\n\n### 🗃️ Project Area\n\nCatalog\n\n### 📝 Description & Context\n\nDeep linking to an endpoint when browsing an Open API definition is not working. Clicking on operation updates the url, however when navigating to the updated url, the page doesn't scroll to the operation.\n\n### 👍 Expected Behavior\n\nGiven a deep link url like https://demo.backstage.io/catalog/default/api/petstore/definition#/user/deleteUser the page should scroll to that operation.\n\n### 🥾 Reproduction steps\n\n1. Click on an endpoint for an openapi swagger docs page\n2. Copy the link and reopen the page OR refresh the page\n3. Find that the endpoint path is expanded, but the page did not scroll to it\n\nThe issue exists on the demo site as well:\nhttps://demo.backstage.io/catalog/default/api/petstore/definition#/user/deleteUser",
    "expected": {
      "labels": [
        "type:bug",
        "area:catalog"
      ],
      "otherLabels": [
        "stale",
        "needs:triage"
      ],
      "related": []
    }
  },
  {
    "id": "#34593",
    "kind": "erro",
    "note": "A busca não traz a documentação certa e a área sai chutada",
    "url": "https://github.com/backstage/backstage/issues/34593",
    "title": "Not documented changes regarding Analytics plugin API",
    "body": "### 🗃️ Project Area\n\nDocumentation\n\n### 📝 Description\n\nI've been using Analytics plugin from backstage for some time now. Recently I noticed that `routeRef` from `AnalyticsEvent ` context isn't registered in my database anymore so I started digging.\n\n1. https://[ref] - I found out docs about analytics are deprecated\n2. https://[ref] - I checked new docs and I noticed we should import stuff regarding analytics from `@backstage/frontend-plugin-api` instead of `@backstage/core-plugin-api`\n3. [ref] - The docs about this page were merged to master on March 17th, that means it was a part of 1.49.0 release\n4. https://github.com/backstage/backstage/releases/tag/v1.49.0 - in the release change log we can read: On the framework side, this release includes significant stabilization of the API surface. Several deprecated types and options have been removed, PluginWrapperApi has graduated from alpha to stable, and a new builder pattern for createApiRef has been introduced. A full list of API changes can be found in the [@backstage/frontend-plugin-api changelog](https://github.com/backstage/backstage/blob/master/packages/frontend-plugin-api/CHANGELOG.md).\n5. https://github.com/backstage/backstage/blob/master/packages/frontend-plugin-api/CHANGELOG.md - in changelog there is only a note about - a321f3b: **BREAKING**: The `CommonAnalyticsContext` has been removed, and inlined into `AnalyticsContextValue` instead. from 19.08.2025, which is something different. Nothing about routeRef in the context of analytics in the whole changelog file.\n\nThe question is how is it possible that API changes that much - I mean, we can't record that data (routeRef in context) anylonger, after update to the newest version, while it was useful for us and there is not a single mention about it anywhere? I also checked migration guide, but there is nothing about analytics - https://[ref]\n\nAm I missing something or was it overlooked?",
    "expected": {
      "labels": [
        "area:documentation"
      ],
      "otherLabels": [
        "contribfest",
        "domain:docs",
        "needs:triage"
      ],
      "related": [
        {
          "id": "doc-frontend-system/building-apps/08-migrating",
          "type": "doc",
          "number": null,
          "title": "frontend-system/building-apps/08-migrating",
          "url": "https://github.com/backstage/backstage/blob/e2fdc2b61fe9046574a8fc1d99b18053018db0a8/docs/frontend-system/building-apps/08-migrating.md"
        },
        {
          "id": "doc-frontend-system/building-plugins/08-analytics",
          "type": "doc",
          "number": null,
          "title": "frontend-system/building-plugins/08-analytics",
          "url": "https://github.com/backstage/backstage/blob/e2fdc2b61fe9046574a8fc1d99b18053018db0a8/docs/frontend-system/building-plugins/08-analytics.md"
        },
        {
          "id": "doc-plugins/analytics",
          "type": "doc",
          "number": null,
          "title": "plugins/analytics",
          "url": "https://github.com/backstage/backstage/blob/e2fdc2b61fe9046574a8fc1d99b18053018db0a8/docs/plugins/analytics.md"
        },
        {
          "id": "pr-21244",
          "type": "pr",
          "number": 21244,
          "title": "[DI] Migrate Analytics Context Files",
          "url": "https://github.com/backstage/backstage/pull/21244"
        },
        {
          "id": "pr-33390",
          "type": "pr",
          "number": 33390,
          "title": "docs: sunset the docs/plugins section as legacy documentation",
          "url": "https://github.com/backstage/backstage/pull/33390"
        }
      ]
    }
  }
];
