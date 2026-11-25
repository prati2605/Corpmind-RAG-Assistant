import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { me } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { Button, ErrorNote, Field, Input, PasswordInput, PageHeader, ROLE_LABEL, formatDate, useToast } from "../components/ui";

export default function SettingsPage() {
  const { user, reloadUser, logout } = useAuth();
  const toast = useToast();
  const [profile, setProfile] = useState({ full_name: user.full_name, department: user.department || "" });
  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });

  const saveProfile = useMutation({
    mutationFn: () => me.update({ full_name: profile.full_name.trim(), department: profile.department.trim() || null }),
    onSuccess: async () => {
      await reloadUser();
      toast("Profile saved");
    },
  });
  const changePw = useMutation({
    mutationFn: () => me.changePassword(pw.current, pw.next),
    onSuccess: async () => {
      toast("Password changed. Sign in again with your new password.");
      await logout();
    },
  });
  const pwProblem =
    pw.next && pw.next.length < 10 ? "Use at least 10 characters." : pw.next && !(/[A-Za-z]/.test(pw.next) && /\d/.test(pw.next)) ? "Include letters and numbers." : null;
  const mismatch = pw.confirm && pw.confirm !== pw.next ? "Passwords don't match." : null;

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Profile and settings" />

      <section className="grid gap-8 border-b border-rule pb-8 md:grid-cols-[13rem_1fr]">
        <div>
          <h2 className="font-semibold">Your details</h2>
          <p className="mt-1 text-sm text-muted">Shown in the sidebar and to administrators.</p>
        </div>
        <form
          className="max-w-md space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            saveProfile.mutate();
          }}
        >
          <Field label="Full name" htmlFor="fn">
            <Input id="fn" value={profile.full_name} maxLength={120} onChange={(e) => setProfile({ ...profile, full_name: e.target.value })} />
          </Field>
          <Field label="Department" htmlFor="dep">
            <Input id="dep" value={profile.department} maxLength={120} onChange={(e) => setProfile({ ...profile, department: e.target.value })} />
          </Field>
          <Field label="Work email" hint="Ask an administrator to change your email.">
            <Input value={user.email} disabled className="bg-paper text-muted" />
          </Field>
          <ErrorNote error={saveProfile.error} />
          <Button type="submit" loading={saveProfile.isPending} disabled={profile.full_name.trim().length < 2}>
            Save changes
          </Button>
        </form>
      </section>

      <section className="grid gap-8 border-b border-rule py-8 md:grid-cols-[13rem_1fr]">
        <div>
          <h2 className="font-semibold">Access</h2>
          <p className="mt-1 text-sm text-muted">Your role decides which document categories CorpMind searches for you.</p>
        </div>
        <div>
          <p>
            You're signed in as <strong className="font-semibold">{ROLE_LABEL[user.role]}</strong>, member since {formatDate(user.created_at)}.
          </p>
          <p className="mt-3 text-sm font-medium text-ink-soft">Categories you can read</p>
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {user.accessible_categories.map((c) => (
              <li key={c} className="rounded-full border border-rule bg-sheet px-2.5 py-0.5 text-sm">
                {c}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-sm text-muted">Need access to more? Ask an administrator to change your role.</p>
        </div>
      </section>

      <section className="grid gap-8 py-8 md:grid-cols-[13rem_1fr]">
        <div>
          <h2 className="font-semibold">Password</h2>
          <p className="mt-1 text-sm text-muted">Changing it signs you out everywhere.</p>
        </div>
        <form
          className="max-w-md space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            changePw.mutate();
          }}
        >
          <Field label="Current password" htmlFor="cur">
            <PasswordInput id="cur" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
          </Field>
          <Field label="New password" htmlFor="new" error={pwProblem} hint="At least 10 characters, with letters and numbers.">
            <PasswordInput id="new" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
          </Field>
          <Field label="Confirm new password" htmlFor="conf" error={mismatch}>
            <PasswordInput id="conf" autoComplete="new-password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} />
          </Field>
          <ErrorNote error={changePw.error} />
          <Button type="submit" loading={changePw.isPending} disabled={!pw.current || !pw.next || !pw.confirm || !!pwProblem || !!mismatch}>
            Change password
          </Button>
        </form>
      </section>
    </div>
  );
}
