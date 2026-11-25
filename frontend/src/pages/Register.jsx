import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { auth } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { Button, ErrorNote, Field, Input, PasswordInput } from "../components/ui";
import AuthShell from "./AuthShell";

export default function RegisterPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ full_name: "", email: "", department: "", password: "", confirm: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const pwProblem =
    form.password && form.password.length < 10
      ? "Use at least 10 characters."
      : form.password && !(/[A-Za-z]/.test(form.password) && /\d/.test(form.password))
        ? "Include both letters and numbers."
        : null;
  const mismatch = form.confirm && form.confirm !== form.password ? "Passwords don't match." : null;

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await auth.register({ full_name: form.full_name, email: form.email, password: form.password, department: form.department || null });
      await login(form.email, form.password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const ready = form.full_name && form.email && form.password && !pwProblem && !mismatch && form.confirm;
  return (
    <AuthShell title="Create your account" subtitle="New accounts start with Employee access. An administrator can change your role.">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Field label="Full name" htmlFor="name">
          <Input id="name" autoComplete="name" value={form.full_name} onChange={set("full_name")} />
        </Field>
        <Field label="Work email" htmlFor="email">
          <Input id="email" type="email" autoComplete="email" value={form.email} onChange={set("email")} />
        </Field>
        <Field label="Department" hint="Optional" htmlFor="dept">
          <Input id="dept" value={form.department} onChange={set("department")} />
        </Field>
        <Field label="Password" htmlFor="pw" error={pwProblem} hint="At least 10 characters, with letters and numbers.">
          <PasswordInput id="pw" autoComplete="new-password" value={form.password} onChange={set("password")} />
        </Field>
        <Field label="Confirm password" htmlFor="pw2" error={mismatch}>
          <PasswordInput id="pw2" autoComplete="new-password" value={form.confirm} onChange={set("confirm")} />
        </Field>
        <ErrorNote error={error} />
        <Button type="submit" className="w-full" loading={busy} disabled={!ready}>
          Create account
        </Button>
      </form>
      <p className="mt-6 text-sm text-muted">
        Already have an account?{" "}
        <Link to="/login" className="font-medium text-ledger underline-offset-2 hover:underline">
          Sign in
        </Link>
      </p>
    </AuthShell>
  );
}
