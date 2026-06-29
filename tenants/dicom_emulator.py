from pydicom.dataset import Dataset
from pynetdicom import AE


def get_modality_worklist():
    # 1. Initialize Application Entity (Modality)
    ae = AE(ae_title="RIS_SCP")

    # 2. Add requested context for Modality Worklist Information Find
    # SOP Class UID: 1.2.840.10008.5.1.4.31
    mwlsop = "1.2.840.10008.5.1.4.31"
    ae.add_requested_context(mwlsop)

    # 3. Build the Query Dataset (Filter)
    ds = Dataset()
    ds.PatientName = "*"
    ds.PatientID = "*"

    # Scheduled Procedure Step Sequence (0040,0100)
    step_seq = Dataset()
    step_seq.ScheduledStationAETitle = "*"
    step_seq.ScheduledProcedureStepStartDate = "20260629"  # Current date
    step_seq.ScheduledProcedureStepStartTime = "000000"
    step_seq.Modality = "*"  # Filter by modality (e.g., CT, MR, CR)
    step_seq.ScheduledProcedureStepDescription = "*"
    step_seq.ScheduledPerformingPhysicianName = "*"

    ds.ScheduledProcedureStepSequence = [step_seq]

    # 4. Define RIS (Worklist SCP) connection parameters
    remote_ip = "0.0.0.0"
    remote_port = 11112
    remote_ae = "RIS_SCP"

    print(f"Connecting to RIS at {remote_ip}:{remote_port}...")
    assoc = ae.associate(remote_ip, remote_port, ae_title=remote_ae)

    if assoc.is_established:
        print("Association established. Sending C-FIND request...\n")

        # 5. Send C-FIND request
        responses = assoc.send_c_find(ds, mwlsop)

        for status, identifier in responses:
            if status:
                # 0xFF00/0xFF01: Pending (Worklist item returned)
                if status.Status in (0xFF00, 0xFF01):
                    print("--- Worklist Item ---")
                    print(f"Patient Name: {identifier.get('PatientName', 'N/A')}")
                    print(f"Patient ID:   {identifier.get('PatientID', 'N/A')}")
                    print(f"Modality:     {identifier.get('Modality', 'N/A')}")
                    print(
                        f"Scheduled:    {identifier.get('ScheduledProcedureStepStartDate', 'N/A')} "
                        f"{identifier.get('ScheduledProcedureStepStartTime', 'N/A')}"
                    )
                    print("-" * 20)
                # 0x0000: Success (Query complete)
                elif status.Status == 0x0000:
                    print("\nWorklist query completed successfully.")
                else:
                    print(f"\nQuery failed. Status: {hex(status.Status)}")
            else:
                print("Connection timed out or was aborted.")
                break

        assoc.release()
    else:
        print("Failed to establish association. Check IP, Port, and AE Title.")


if __name__ == "__main__":
    get_modality_worklist()
