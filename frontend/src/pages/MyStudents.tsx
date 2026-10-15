/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { analyticsApi, instructorsApi, type Role } from "../api";
import { Card, Empty, ErrorBox, Select } from "../components/ui";
import { AnalyticsView } from "./Analytics";
import { PageSkeleton } from "../components/skeletons";

/** An instructor's own students. Admins pick which instructor's view to see. */
export default function MyStudents({ role, name }: { role: Role; name: string | null }) {
  if (role === "admin") return <AdminPreview />;
  return (
    <AnalyticsView
      title="My students"
      subtitle={`${name ? `${name}, here` : "Here"} is how the students assigned to you are doing: toppers, attendance, consistency, question by question.`}
      queryKey={["instructor-analytics", "me"]}
      fetch={(f) => analyticsApi.instructor(f)}
      fetchStudents={(f, page) => analyticsApi.instructorStudents(f, page)}
    />
  );
}

function AdminPreview() {
  const [params, setParams] = useSearchParams();
  const list = useQuery({ queryKey: ["instructors"], queryFn: instructorsApi.list });
  const id = Number(params.get("instructor")) || list.data?.instructors[0]?.id;
  const current = list.data?.instructors.find((i) => i.id === id);

  if (list.isPending) return <PageSkeleton />;
  if (list.isError) return <ErrorBox error={list.error} />;
  if (!current)
    return (
      <Card>
        <Empty>No instructors yet. Add one on the Admin page.</Empty>
      </Card>
    );

  return (
    <AnalyticsView
      key={current.id}
      title={`${current.name}'s students`}
      subtitle={`What ${current.name} sees on their “My students” page · ${current.students} students.`}
      queryKey={["instructor-analytics", current.id]}
      fetch={(f) => analyticsApi.instructor(f, current.id)}
      fetchStudents={(f, page) => analyticsApi.instructorStudents(f, page, current.id)}
      actions={
        <Select label="Instructor" value={current.id} onChange={(e) => setParams({ instructor: e.target.value })}>
          {list.data.instructors.map((i) => (
            <option key={i.id} value={i.id}>
              {i.name}
            </option>
          ))}
        </Select>
      }
    />
  );
}
