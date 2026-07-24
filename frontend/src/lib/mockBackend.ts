/**
 * Dev-only mock backend. Patches window.fetch to answer /v1/* locally so the
 * UI can be reviewed without a running API. Installed from main.tsx ONLY when
 * import.meta.env.DEV is true AND VITE_MOCK === "1", so production builds tree-
 * shake it away entirely. Never import this from production code paths.
 */
import type {
  AdminUser,
  ApiKey,
  Artifact,
  Job,
  JobMessage,
  RuntimeConfig,
  User,
} from "../types";

let loggedIn = false;

const adminUser: User = {
  id: "u-admin",
  username: "admin",
  is_admin: true,
  org_id: null,
};

const now = Date.now();
const iso = (offsetMs: number) => new Date(now - offsetMs).toISOString();

const jobs: Job[] = [
  {
    id: "job-1",
    title: "新能源汽车市场分析",
    prompt: "帮我做一份新能源汽车市场分析的演示",
    route: "generate_pptx",
    status: "succeeded",
    stage: "succeeded",
    progress: 100,
    cancel_requested: false,
    error: null,
    created_at: iso(3_600_000),
    updated_at: iso(3_000_000),
    files_purged_at: null,
  },
  {
    id: "job-2",
    title: "季度产品路线图",
    prompt: "根据这份文档生成季度产品路线图",
    route: "generate_pptx",
    status: "executing",
    stage: "executing",
    progress: 45,
    cancel_requested: false,
    error: null,
    created_at: iso(600_000),
    updated_at: iso(120_000),
    files_purged_at: null,
  },
  {
    id: "job-3",
    title: "团队 OKR 汇报",
    prompt: "把这些要点做成 OKR 汇报",
    route: "generate_pptx",
    status: "awaiting_confirmation",
    stage: "awaiting_confirmation",
    progress: 20,
    cancel_requested: false,
    error: null,
    created_at: iso(300_000),
    updated_at: iso(60_000),
    files_purged_at: null,
  },
];

const messages: Record<string, JobMessage[]> = {
  "job-1": [
    {
      id: 1,
      job_id: "job-1",
      role: "user",
      content: "帮我做一份新能源汽车市场分析的演示，10 页左右。",
      created_at: iso(3_600_000),
    },
    {
      id: 2,
      job_id: "job-1",
      role: "assistant",
      content:
        "已完成 10 页演示，涵盖市场规模、竞争格局、增长驱动与风险。\n\n- 封面与目录\n- 市场规模与预测\n- 主要厂商对比\n- 政策与趋势\n- 结论与建议",
      created_at: iso(3_050_000),
    },
  ],
  "job-2": [
    {
      id: 3,
      job_id: "job-2",
      role: "user",
      content: "根据这份文档生成季度产品路线图。",
      created_at: iso(600_000),
    },
  ],
  "job-3": [
    {
      id: 4,
      job_id: "job-3",
      role: "user",
      content: "把这些要点做成 OKR 汇报。",
      created_at: iso(300_000),
    },
    {
      id: 5,
      job_id: "job-3",
      role: "assistant",
      content:
        "我准备了如下方案，请确认后开始生成页面：\n\n1. 目标概述\n2. 关键结果拆解\n3. 进度与风险",
      created_at: iso(120_000),
    },
  ],
};

const adminUsers: AdminUser[] = [
  {
    id: "u-admin",
    username: "admin",
    is_admin: true,
    disabled: false,
    active_api_key_count: 2,
    created_at: iso(30 * 86_400_000),
    updated_at: iso(86_400_000),
  },
  {
    id: "u-alice",
    username: "alice",
    is_admin: false,
    disabled: false,
    active_api_key_count: 1,
    created_at: iso(10 * 86_400_000),
    updated_at: iso(2 * 86_400_000),
  },
  {
    id: "u-bob",
    username: "bob",
    is_admin: false,
    disabled: true,
    active_api_key_count: 0,
    created_at: iso(5 * 86_400_000),
    updated_at: iso(86_400_000),
  },
  // Extra demo accounts so the table pagination is visible (13 total → 2 pages).
  ...Array.from({ length: 10 }, (_, i) => ({
    id: `u-demo-${i}`,
    username: `user_${String(i + 1).padStart(2, "0")}`,
    is_admin: false,
    disabled: i % 4 === 3,
    active_api_key_count: i % 3,
    created_at: iso((i + 1) * 43_200_000),
    updated_at: iso((i + 1) * 21_600_000),
  })),
];

const runtimeConfig: RuntimeConfig = {
  codex_base_url: "https://api.example.com/v1",
  codex_api_key_configured: true,
  codex_model: "gpt-5",
  image_base_url: "https://prism.example.com/v1",
  image_api_key_configured: true,
  image_model: "gpt-image-2",
  image_size: "2048x1536",
  image_concurrency: null,
  updated_at: iso(86_400_000),
};

const apiKeys: ApiKey[] = [
  {
    id: "k-1",
    name: "第三方调用",
    key_prefix: "ppt_live_a1b2",
    last_used_at: iso(86_400_000),
    revoked_at: null,
    created_at: iso(20 * 86_400_000),
  },
];

const pricing = {
  price_input_token: 0.000002,
  price_output_token: 0.000008,
  price_image: 0.25,
  hold_amount: 5,
};

const orgs = [
  {
    id: "org-1",
    name: "示例科技有限公司",
    slug: "example-tech",
    credit_balance: 1280.5,
    daily_job_limit: 100,
    max_active_jobs: 5,
    created_at: iso(20 * 86_400_000),
  },
  {
    id: "org-2",
    name: "未来教育集团",
    slug: "future-edu",
    credit_balance: 42,
    daily_job_limit: 200,
    max_active_jobs: 8,
    created_at: iso(8 * 86_400_000),
  },
];

const orgKeys: Record<string, unknown[]> = {
  "org-1": [
    {
      id: "ok-1",
      name: "组织服务密钥",
      key_prefix: "ppt_org_9f3c",
      last_used_at: iso(3_600_000),
      revoked_at: null,
      created_at: iso(20 * 86_400_000),
    },
  ],
  "org-2": [],
};

const orgUsage: Record<string, unknown[]> = {
  "org-1": [
    {
      end_user_id: "student_001",
      input_tokens: 128_400,
      output_tokens: 45_200,
      images: 12,
      pages: 30,
      our_charge: 6.4,
      jobs: 3,
    },
    {
      end_user_id: "student_002",
      input_tokens: 88_100,
      output_tokens: 31_500,
      images: 8,
      pages: 20,
      our_charge: 4.1,
      jobs: 2,
    },
    {
      end_user_id: null,
      input_tokens: 12_000,
      output_tokens: 4_000,
      images: 1,
      pages: 4,
      our_charge: 0.5,
      jobs: 1,
    },
  ],
  "org-2": [],
};

const SLIDE_SVG = (n: number, label: string) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
    <rect width="1280" height="720" fill="#f5faf8"/>
    <rect x="0" y="0" width="1280" height="120" fill="#4f9e8c"/>
    <text x="64" y="78" font-family="sans-serif" font-size="44" fill="#fff" font-weight="700">${label}</text>
    <text x="64" y="360" font-family="sans-serif" font-size="120" fill="#bfd8d0" font-weight="800">${n}</text>
    <rect x="64" y="440" width="640" height="18" rx="9" fill="#d7e8e2"/>
    <rect x="64" y="484" width="520" height="18" rx="9" fill="#e8f1ee"/>
    <rect x="64" y="528" width="580" height="18" rx="9" fill="#e8f1ee"/>
  </svg>`;

const artifacts: Record<string, Artifact[]> = {
  "job-1": [
    ...[1, 2, 3, 4].map((n) => ({
      id: `job-1-p${n}`,
      job_id: "job-1",
      kind: "preview" as const,
      filename: `slide-${n}.svg`,
      size_bytes: 4200,
      sha256: `hash${n}`,
      media_type: "image/svg+xml",
      created_at: iso(3_050_000),
    })),
    {
      id: "job-1-pptx",
      job_id: "job-1",
      kind: "pptx",
      filename: "新能源汽车市场分析.pptx",
      size_bytes: 2_340_000,
      sha256: "hashpptx",
      media_type:
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      created_at: iso(3_000_000),
    },
  ],
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function route(method: string, path: string): Response {
  // Auth
  if (path === "/v1/auth/me")
    return loggedIn ? json(adminUser) : json({ detail: "未登录" }, 401);
  if (path === "/v1/auth/login" && method === "POST") {
    loggedIn = true;
    return json(adminUser);
  }
  if (path === "/v1/auth/org-tickets/consume" && method === "POST") {
    loggedIn = true;
    return json(adminUser);
  }
  if (path === "/v1/auth/logout" && method === "POST") {
    loggedIn = false;
    return json({ ok: true });
  }
  if (path === "/v1/auth/api-keys" && method === "GET") return json(apiKeys);
  if (path === "/v1/auth/api-keys" && method === "POST")
    return json({
      id: `k-${Date.now()}`,
      name: "第三方调用",
      key_prefix: "ppt_live_new0",
      last_used_at: null,
      revoked_at: null,
      created_at: new Date().toISOString(),
      key: "ppt_live_new0_DEMO_ONLY_not_a_real_key",
    });

  // Admin
  if (path === "/v1/admin/users" && method === "GET") return json(adminUsers);
  if (path === "/v1/admin/runtime-config") return json(runtimeConfig);

  // Billing / pricing
  if (path === "/v1/admin/billing-config") return json(pricing);

  // Organizations
  if (path === "/v1/admin/orgs" && method === "GET") return json(orgs);
  if (path === "/v1/admin/orgs" && method === "POST") {
    const org = {
      id: `org-${Date.now()}`,
      name: "新建组织",
      slug: `org-${Date.now()}`,
      credit_balance: 0,
      daily_job_limit: 100,
      max_active_jobs: 5,
      created_at: new Date().toISOString(),
    };
    orgs.unshift(org);
    return json(org, 201);
  }
  const orgMatch = path.match(/^\/v1\/admin\/orgs\/([^/]+)\/(\w+)$/);
  if (orgMatch) {
    const [, orgId, sub] = orgMatch;
    if (sub === "keys" && method === "GET") return json(orgKeys[orgId] ?? []);
    if (sub === "keys" && method === "POST")
      return json(
        {
          id: `ok-${Date.now()}`,
          name: "组织服务密钥",
          key_prefix: "ppt_org_new0",
          last_used_at: null,
          revoked_at: null,
          created_at: new Date().toISOString(),
          key: "ppt_org_new0_DEMO_ONLY_not_a_real_key",
        },
        201,
      );
    if (sub === "credits" && method === "POST")
      return json({ org_id: orgId, credit_balance: 9999 });
    if (sub === "usage" && method === "GET")
      return json({ org_id: orgId, end_users: orgUsage[orgId] ?? [] });
  }

  // Jobs
  if (path === "/v1/jobs" && method === "GET") return json(jobs);
  const jobMatch = path.match(/^\/v1\/jobs\/([^/]+)(\/(\w+))?$/);
  if (jobMatch) {
    const [, id, , sub] = jobMatch;
    if (!sub) return json(jobs.find((j) => j.id === id) ?? {}, 200);
    if (sub === "messages") return json(messages[id] ?? []);
    if (sub === "artifacts") return json(artifacts[id] ?? []);
    if (sub === "confirmation")
      return id === "job-3"
        ? json({
            job_id: id,
            proposal: {
              markdown: "## 方案\n1. 目标概述\n2. 关键结果\n3. 进度风险",
            },
            response: null,
            status: "pending",
            created_at: iso(120_000),
            updated_at: iso(120_000),
          })
        : json({ detail: "无确认" }, 404);
  }

  return json({ detail: `mock 未覆盖: ${method} ${path}` }, 404);
}

/** Install the dev mock. Idempotent; safe to call once from main.tsx. */
export function installMockBackend() {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = typeof input === "string" ? input : (input as Request).url;
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    const method = (init?.method || "GET").toUpperCase();
    if (!path.startsWith("/v1/")) return nativeFetch(input, init);

    // SSE progress stream — return an empty, immediately-idle stream.
    if (/\/events$/.test(path)) {
      return new Response(new ReadableStream(), {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      });
    }
    // Preview / artifact blobs — hand back a rendered demo slide.
    const blobMatch = path.match(/\/artifacts\/([^/]+)\/(view|download)$/);
    if (blobMatch) {
      const n = Number(blobMatch[1].replace(/\D/g, "")) || 1;
      const type = blobMatch[1].includes("pptx")
        ? "application/octet-stream"
        : "image/svg+xml";
      const body = type === "image/svg+xml" ? SLIDE_SVG(n, "演示预览") : "demo";
      return new Response(body, {
        status: 200,
        headers: { "Content-Type": type },
      });
    }

    await new Promise((r) => setTimeout(r, 120)); // tiny latency for realism
    return route(method, path);
  };
  console.info(
    "%c[mock] 假后端已启用 — 任意用户名/密码即可登录（仅开发模式）",
    "color:#4f9e8c;font-weight:700",
  );
}
