import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Facility',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=150)),
                ('address', models.TextField(blank=True)),
                ('contact_phone', models.CharField(blank=True, max_length=30)),
                ('dicom_ae_title', models.CharField(max_length=16, unique=True)),
                ('hl7_facility_id', models.CharField(blank=True, max_length=50)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Modality',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('code', models.CharField(choices=[('AU', 'Audio'), ('BD', 'Biomagnetic Device'), ('BI', 'Biosignal'), ('CD', 'Confocal Microscopy'), ('CR', 'Computed Radiography'), ('CT', 'Computed Tomography'), ('DG', 'Diaphanography'), ('DX', 'Digital Radiography'), ('ECG', 'Electrocardiography'), ('EPS', 'Cardiac Electrophysiology'), ('ES', 'Endoscopy'), ('FID', 'Fiducials'), ('GM', 'General Microscopy'), ('HC', 'Hard Copy'), ('HD', 'Hemodynamic Waveform'), ('IO', 'Intra-oral Radiography'), ('IVUS', 'Intravascular Ultrasound'), ('KO', 'Key Object Selection'), ('LS', 'Laser Surface Scan'), ('MG', 'Mammography'), ('MR', 'Magnetic Resonance'), ('NM', 'Nuclear Medicine'), ('OP', 'Ophthalmic Photography'), ('OPM', 'Ophthalmic Mapping'), ('OPT', 'Ophthalmic Tomography'), ('OSS', 'Optical Surface Scan'), ('OT', 'Other'), ('PX', 'Panoramic X-Ray'), ('PT', 'Positron Emission Tomography'), ('RG', 'Radiographic Imaging'), ('RF', 'Radio Fluoroscopy'), ('RTDOSE', 'Radiotherapy Dose'), ('RTIMAGE', 'Radiotherapy Image'), ('RTPLAN', 'Radiotherapy Plan'), ('RTRECORD', 'Radiotherapy Record'), ('RTSTRUCT', 'Radiotherapy Structure Set'), ('RWV', 'Real World Value Map'), ('SC', 'Secondary Capture'), ('SM', 'Slide Microscopy'), ('SMR', 'Stereometric Radiography'), ('SR', 'Structured Report'), ('STAIN', 'Staining'), ('TG', 'Thermography'), ('US', 'Ultrasound'), ('VA', 'Visual Acuity'), ('XC', 'External Camera Photography'), ('XA', 'X-Ray Angiography')], max_length=10)),
                ('name', models.CharField(blank=True, max_length=50)),
                ('description', models.TextField(blank=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['code'],
            },
        ),
        migrations.CreateModel(
            name='Device',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=150)),
                ('room_number', models.CharField(blank=True, max_length=50)),
                ('dicom_ae_title', models.CharField(default='DEVICE', help_text='DICOM AE Title of the device', max_length=16)),
                ('dicom_host', models.GenericIPAddressField(help_text='IP address or hostname of the DICOM device')),
                ('dicom_port', models.PositiveIntegerField(default=104, help_text='DICOM port number')),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('facility', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.CASCADE, related_name='devices', to='core.facility')),
                ('modality', models.ForeignKey(on_delete=models.deletion.PROTECT, related_name='devices', to='core.modality')),
            ],
            options={
                'ordering': ['name'],
            },
        ),
    ]
