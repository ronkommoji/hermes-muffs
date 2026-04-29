import { useCallback, useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  CheckCircle2,
  ExternalLink,
  Plug,
  RefreshCw,
  AlertTriangle,
} from "lucide-react";
import { api } from "@/lib/api";
import type { IntegrationsResponse } from "@/lib/api";
import { Button, Spinner } from "@nous-research/ui";
import { Badge } from "@nous-research/ui";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/useToast";
import { useI18n } from "@/i18n";
import { PluginSlot } from "@/plugins";
import { cn } from "@/lib/utils";

const G_LINK_APIS = "https://console.cloud.google.com/apis/library";
const G_LINK_CREDS = "https://console.cloud.google.com/apis/credentials";
const GH_LINK_TOKENS = "https://github.com/settings/tokens";

function StepList({ children }: { children: React.ReactNode }) {
  return (
    <ol className="mt-3 list-decimal space-y-2 pl-4 text-sm leading-relaxed text-muted-foreground">
      {children}
    </ol>
  );
}

export default function IntegrationsPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [data, setData] = useState<IntegrationsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  const [googleJson, setGoogleJson] = useState("");
  const [googleCode, setGoogleCode] = useState("");
  const [githubPat, setGithubPat] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await api.getIntegrations();
      setData(resp);
    } catch (e) {
      showToast(`${t.integrations.saveFailed}: ${e}`, "error");
    } finally {
      setLoading(false);
    }
  }, [showToast, t.integrations.saveFailed]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    try {
      await fn();
      await refresh();
    } catch (e) {
      showToast(`${t.integrations.saveFailed}: ${e}`, "error");
    } finally {
      setBusy(null);
    }
  };

  const google = data?.google_workspace;
  const gh = data?.github;
  const mcp = data?.mcp;

  const googleBadge = !google ? null : google.authenticated ? (
    <Badge tone={google.partial_scopes ? "warning" : "success"} className="text-[11px]">
      {google.partial_scopes
        ? t.integrations.googleStatusPartial
        : t.integrations.googleStatusOk}
    </Badge>
  ) : google.has_client_secret ? (
    <Badge tone="outline" className="text-[11px]">
      {t.integrations.googleNotSignedIn}
    </Badge>
  ) : (
    <Badge tone="outline" className="text-[11px]">
      {t.integrations.googleStatusNeedSecret}
    </Badge>
  );

  const githubBadge = !gh ? null : gh.connected ? (
    <Badge tone="success" className="text-[11px]">
      {gh.gh_cli_authenticated
        ? t.integrations.githubStatusCli
        : t.integrations.githubStatusToken}
    </Badge>
  ) : (
    <Badge tone="outline" className="text-[11px]">
      {t.integrations.githubStatusNone}
    </Badge>
  );

  return (
    <>
      <PluginSlot name="integrations:top" />
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto p-4 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <div className="flex items-center gap-2">
              <Plug className="h-5 w-5 text-primary" aria-hidden />
              <h2 className="text-lg font-semibold text-midground">
                {t.app.nav.integrations}
              </h2>
            </div>
            <p className="max-w-2xl text-sm text-muted-foreground">
              {t.integrations.subtitle}
            </p>
          </div>
          <Button
            size="sm"
            outlined
            onClick={() => refresh()}
            disabled={loading}
            prefix={loading ? <Spinner /> : <RefreshCw className="h-4 w-4" />}
          >
            {t.common.refresh}
          </Button>
        </div>

        {loading && !data ? (
          <div className="flex flex-1 items-center justify-center py-20">
            <Spinner className="text-2xl text-primary" />
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="border-border/60 shadow-sm">
              <CardHeader className="pb-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle className="text-base">{t.integrations.googleTitle}</CardTitle>
                  {googleBadge}
                </div>
                <CardDescription>{t.integrations.googleBlurb}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <StepList>
                  <li>
                    {t.integrations.googleStep1}{" "}
                    <a
                      href={G_LINK_APIS}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-0.5 font-medium text-primary hover:underline"
                    >
                      {t.integrations.linkConsole}
                      <ExternalLink className="h-3 w-3 opacity-70" />
                    </a>
                  </li>
                  <li>
                    {t.integrations.googleStep2}{" "}
                    <a
                      href={G_LINK_CREDS}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-0.5 font-medium text-primary hover:underline"
                    >
                      {t.integrations.linkConsole}
                      <ExternalLink className="h-3 w-3 opacity-70" />
                    </a>
                  </li>
                  <li>{t.integrations.googleStep3}</li>
                </StepList>

                <div className="space-y-2">
                  <Label htmlFor="g-json">{t.integrations.googleSecretLabel}</Label>
                  <p className="text-xs text-muted-foreground">
                    {t.integrations.googleSecretHelp}
                  </p>
                  <textarea
                    id="g-json"
                    value={googleJson}
                    onChange={(e) => setGoogleJson(e.target.value)}
                    spellCheck={false}
                    rows={6}
                    className={cn(
                      "w-full resize-y rounded-md border border-border bg-background px-3 py-2",
                      "font-mono text-xs leading-relaxed text-foreground",
                      "placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring",
                    )}
                    placeholder='{"installed":{...}}'
                  />
                  <Button
                    size="sm"
                    onClick={() =>
                      run("g-save", async () => {
                        await api.saveGoogleWorkspaceClientSecret(googleJson);
                        showToast(t.integrations.googleSaveSecret, "success");
                      })
                    }
                    disabled={!googleJson.trim() || busy !== null}
                    prefix={busy === "g-save" ? <Spinner /> : undefined}
                  >
                    {t.integrations.googleSaveSecret}
                  </Button>
                </div>

                <div className="flex flex-wrap gap-2 border-t border-border/50 pt-4">
                  <Button
                    size="sm"
                    outlined
                    onClick={() =>
                      run("g-url", async () => {
                        const r = await api.getGoogleWorkspaceAuthUrl();
                        window.open(r.auth_url, "_blank", "noopener,noreferrer");
                        showToast(t.integrations.googleAuthOpened, "success");
                      })
                    }
                    disabled={busy !== null || !google?.has_client_secret}
                    prefix={
                      busy === "g-url" ? (
                        <Spinner />
                      ) : (
                        <ExternalLink className="h-4 w-4" />
                      )
                    }
                  >
                    {t.integrations.googleOpenConsent}
                  </Button>
                  <Button
                    size="sm"
                    outlined
                    onClick={() =>
                      run("g-url-only", async () => {
                        const r = await api.getGoogleWorkspaceAuthUrl();
                        await navigator.clipboard.writeText(r.auth_url);
                        showToast(t.integrations.googleAuthLinkCopied, "success");
                      })
                    }
                    disabled={busy !== null || !google?.has_client_secret}
                    prefix={busy === "g-url-only" ? <Spinner /> : undefined}
                  >
                    {t.integrations.googleGetLink}
                  </Button>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="g-code">{t.integrations.googleCodeLabel}</Label>
                  <p className="text-xs text-muted-foreground">
                    {t.integrations.googleCodeHelp}
                  </p>
                  <textarea
                    id="g-code"
                    value={googleCode}
                    onChange={(e) => setGoogleCode(e.target.value)}
                    rows={3}
                    className={cn(
                      "w-full resize-y rounded-md border border-border bg-background px-3 py-2",
                      "font-mono text-xs text-foreground",
                      "focus-visible:ring-2 focus-visible:ring-ring",
                    )}
                  />
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      onClick={() =>
                        run("g-ex", async () => {
                          await api.finishGoogleWorkspaceOAuth(googleCode.trim());
                          setGoogleCode("");
                          showToast(t.integrations.googleFinish, "success");
                        })
                      }
                      disabled={!googleCode.trim() || busy !== null}
                      prefix={busy === "g-ex" ? <Spinner /> : undefined}
                    >
                      {t.integrations.googleFinish}
                    </Button>
                    <Button
                      size="sm"
                      outlined
                      onClick={async () => {
                        if (!confirm(t.integrations.googleRevokeConfirm)) return;
                        await run("g-rev", async () => {
                          await api.revokeGoogleWorkspace();
                          showToast(t.integrations.googleRevoke, "success");
                        });
                      }}
                      disabled={busy !== null}
                      prefix={busy === "g-rev" ? <Spinner /> : undefined}
                    >
                      {t.integrations.googleRevoke}
                    </Button>
                  </div>
                </div>

                {google?.detail && (
                  <pre className="max-h-32 overflow-auto rounded-md bg-secondary/30 p-2 text-[11px] text-muted-foreground">
                    {google.detail}
                  </pre>
                )}
              </CardContent>
            </Card>

            <div className="flex flex-col gap-4">
              <Card className="border-border/60 shadow-sm">
                <CardHeader className="pb-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <CardTitle className="text-base">{t.integrations.githubTitle}</CardTitle>
                    {githubBadge}
                  </div>
                  <CardDescription>{t.integrations.githubBlurb}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <StepList>
                    <li>
                      {t.integrations.githubStep1}{" "}
                      <a
                        href={GH_LINK_TOKENS}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-0.5 font-medium text-primary hover:underline"
                      >
                        {t.integrations.linkPat}
                        <ExternalLink className="h-3 w-3 opacity-70" />
                      </a>
                    </li>
                  </StepList>
                  {!gh?.connected && gh?.gh_hint ? (
                    <p className="flex items-start gap-2 text-xs text-muted-foreground">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
                      {gh.gh_hint}
                    </p>
                  ) : null}
                  <div className="space-y-2">
                    <Label htmlFor="gh-pat">{t.integrations.githubPatLabel}</Label>
                    <input
                      id="gh-pat"
                      type="password"
                      autoComplete="off"
                      value={githubPat}
                      onChange={(e) => setGithubPat(e.target.value)}
                      className={cn(
                        "w-full rounded-md border border-border bg-background px-3 py-2",
                        "font-mono text-sm text-foreground",
                        "focus-visible:ring-2 focus-visible:ring-ring",
                      )}
                      placeholder="ghp_…"
                    />
                    <Button
                      size="sm"
                      onClick={() =>
                        run("gh-save", async () => {
                          await api.saveGitHubPat(githubPat.trim());
                          setGithubPat("");
                          showToast(t.integrations.githubSavePat, "success");
                        })
                      }
                      disabled={!githubPat.trim() || busy !== null}
                      prefix={busy === "gh-save" ? <Spinner /> : undefined}
                    >
                      {t.integrations.githubSavePat}
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    <NavLink to="/env" className="text-primary hover:underline">
                      {t.app.nav.keys}
                    </NavLink>{" "}
                    — manage or reveal stored values.
                  </p>
                </CardContent>
              </Card>

              <Card className="border-border/60 shadow-sm">
                <CardHeader className="pb-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <CardTitle className="text-base">{t.integrations.mcpTitle}</CardTitle>
                    {mcp?.configured ? (
                      <Badge tone="success" className="text-[11px]">
                        {t.integrations.mcpCount.replace(
                          "{count}",
                          String(mcp.server_count),
                        )}
                      </Badge>
                    ) : (
                      <Badge tone="outline" className="text-[11px]">
                        —
                      </Badge>
                    )}
                  </div>
                  <CardDescription>{t.integrations.mcpBlurb}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  {mcp?.server_names?.length ? (
                    <ul className="flex flex-wrap gap-1.5">
                      {mcp.server_names.map((n) => (
                        <Badge key={n} tone="outline" className="font-mono text-[11px]">
                          {n}
                        </Badge>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-muted-foreground">—</p>
                  )}
                  <Button size="sm" outlined onClick={() => navigate("/config")}>
                    {t.integrations.mcpOpenYaml}
                  </Button>
                </CardContent>
              </Card>

              <Card className="border-border/60 bg-secondary/10 shadow-sm">
                <CardHeader className="pb-2">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-success" />
                    <CardTitle className="text-base">{t.integrations.moreTitle}</CardTitle>
                  </div>
                  <CardDescription>{t.integrations.moreBlurb}</CardDescription>
                </CardHeader>
                <CardContent className="flex flex-wrap gap-2">
                  <Button size="sm" outlined onClick={() => navigate("/env")}>
                    {t.integrations.moreOAuthCard}
                  </Button>
                  <Button size="sm" outlined onClick={() => navigate("/skills")}>
                    {t.integrations.moreSkillsCard}
                  </Button>
                </CardContent>
              </Card>
            </div>
          </div>
        )}
      </div>
      <PluginSlot name="integrations:bottom" />
    </>
  );
}
