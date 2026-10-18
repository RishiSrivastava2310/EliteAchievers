import { useState } from 'react';
import { Plus, Users, Clock3, Database } from 'lucide-react';
import { useStore } from '../lib/store';
import { PageTitle, Button } from '../components/ui';
import { PatientTable } from '../components/PatientTable';
import { DataEntry } from '../components/DataEntry';
export function Patients() {
  const { data, hour, mode } = useStore();
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState('All sources');
  const [risk, setRisk] = useState('All risks');
  const [status, setStatus] = useState('All statuses');
  return (
    <>
      <PageTitle
        eyebrow="PATIENT DIRECTORY"
        title="Patient directory"
        icon={Users}
        description="Search de-identified ICU stays and review their available history."
        actions={
          mode === 'synthetic' && (
            <Button onClick={() => setOpen(true)}>
              <Plus size={17} />
              Add synthetic stay
            </Button>
          )
        }
      />
      <div className="directory-summary">
        <span className="directory-total">
          <Users size={18} />
          <b>{data?.patients.length ?? 0}</b>loaded ICU stays
        </span>
        <span>
          <Clock3 size={18} />
          Selected replay: <b>ICU hour {hour}</b>
        </span>
        <span>
          <Database size={18} />
          Sources <b>{new Set(data?.patients.map((p) => p.source)).size}</b>
        </span>
      </div>
      <PatientTable
        source={source}
        onSource={setSource}
        risk={risk}
        onRisk={setRisk}
        status={status}
        onStatus={setStatus}
      />
      <DataEntry open={open} onOpenChange={setOpen} />
    </>
  );
}
