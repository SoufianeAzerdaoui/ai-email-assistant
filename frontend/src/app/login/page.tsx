import { Mail } from "lucide-react";

import { LoginForm } from "@/components/login-form";

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12">
      <div className="w-full max-w-[400px]">
        <div className="mb-8 flex items-center justify-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-lg bg-blue-600 text-white">
            <Mail className="size-5" strokeWidth={1.8} />
          </span>
          <span className="text-lg font-semibold tracking-tight text-slate-900">Mailflow</span>
        </div>
        <section className="rounded-lg border border-slate-200 bg-white p-6 sm:p-8">
          <div className="mb-6">
            <h1 className="text-xl font-semibold tracking-tight text-slate-900">Bon retour</h1>
            <p className="mt-1.5 text-sm leading-6 text-slate-500">
              Connectez-vous pour accéder à votre boîte de réception.
            </p>
          </div>
          <LoginForm />
        </section>
        <p className="mt-5 text-center text-xs text-slate-400">
          Accès réservé aux comptes créés par un administrateur.
        </p>
      </div>
    </main>
  );
}
