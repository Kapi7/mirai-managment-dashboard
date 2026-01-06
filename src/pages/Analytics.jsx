import React from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BarChart3 } from "lucide-react";

export default function Analytics() {
  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Analytics</h1>
        <p className="text-slate-500 mt-1">Advanced analytics and insights</p>
      </div>

      <Card className="border-slate-200">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BarChart3 className="w-5 h-5" />
            Coming Soon
            <Badge variant="secondary" className="ml-auto">In Development</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-slate-600">
            Advanced analytics with charts, trends, and performance insights are coming soon.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}