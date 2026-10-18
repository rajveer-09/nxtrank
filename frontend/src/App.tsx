/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { Suspense, useEffect } from "react";
import { warmDatabase } from "./api";
import { Navigate, Route, Routes } from "react-router-dom";
import { useMe } from "./auth";
import Layout from "./components/Layout";
import { Brand } from "./components/Layout";
import { Button } from "./components/ui";
import { pages, preloadWhenIdle } from "./routes";
import { PageSkeleton } from "./components/skeletons";

const { Admin, Analytics, ContestPage, Contests, Guide, Login, MyStudents, StudentPage, Students } = pages;

function Splash() {
  return (
    <div className="splash grid min-h-screen place-items-center" role="status" aria-label="Loading">
      <div className="flex flex-col items-center gap-5">
        <Brand size="lg" />
        <span aria-hidden className="splash-bar" />
      </div>
    </div>
  );
}

/** Back on the tab after a while: the database has probably gone to sleep, so start
 *  waking it before the page's own requests need it. */
const AWAY_BEFORE_WARM_MS = 4 * 60_000;

function useWarmOnReturn() {
  useEffect(() => {
    let hiddenAt = document.hidden ? Date.now() : 0;
    const onChange = () => {
      if (document.hidden) hiddenAt = Date.now();
      else if (hiddenAt && Date.now() - hiddenAt > AWAY_BEFORE_WARM_MS) warmDatabase();
    };
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);
}

export default function App() {
  useWarmOnReturn();
  const me = useMe();
  const role = me.data?.role;

  // once signed in, fetch the other pages' code in the background
  useEffect(() => {
    if (!role) return;
    preloadWhenIdle([
      Contests.preload, ContestPage.preload, Analytics.preload, Students.preload, StudentPage.preload, Guide.preload,
      ...(role === "admin" ? [Admin.preload] : []),
      ...(role !== "viewer" ? [MyStudents.preload] : []),
    ]);
  }, [role]);

  if (me.isPending) return <Splash />;
  if (me.isError)
    return (
      <div className="grid min-h-screen place-items-center px-4">
        <div className="rise flex max-w-sm flex-col items-center gap-4 text-center">
          <Brand size="lg" />
          <div>
            <h1 className="text-[15px] font-semibold text-ink">Can't reach the dashboard</h1>
            <p className="mt-1 text-[13px] text-ink-2">The server isn't answering. Check your connection, or try again in a moment.</p>
          </div>
          <Button variant="primary" onClick={() => me.refetch()} disabled={me.isFetching}>
            {me.isFetching ? "Trying…" : "Try again"}
          </Button>
        </div>
      </div>
    );
  if (!me.data)
    return (
      <Suspense fallback={<Splash />}>
        <Login />
      </Suspense>
    );

  return (
    <Layout me={me.data}>
      <Suspense fallback={<PageSkeleton />}>
      <Routes>
        <Route path="/" element={<Contests isAdmin={me.data.role === "admin"} />} />
        <Route path="/contests/:slug" element={<ContestPage isAdmin={me.data.role === "admin"} />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/students" element={<Students />} />
        <Route path="/students/:id" element={<StudentPage />} />
        <Route path="/guide" element={<Guide />} />
        {me.data.role === "admin" && <Route path="/admin/*" element={<Admin />} />}
        {(me.data.role === "admin" || me.data.role === "instructor") && (
          <Route path="/my-students" element={<MyStudents role={me.data.role} name={me.data.name} />} />
        )}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </Suspense>
    </Layout>
  );
}
