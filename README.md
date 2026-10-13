# MediSync SA

## Overview

**MediSync SA** is a Django-based clinic management system designed for South African healthcare facilities. It provides a unified platform for patients, doctors, nurses, receptionists, and administrators to manage appointments, medical records, prescriptions, referrals, and follow-ups.

The system uses **South African ID numbers** for patient identification, **OTP-based login** (via SMS) for authentication, and **MySQL stored procedures** to enforce critical business rules such as preventing double-bookings.

### Methodologies & Practices

1. **Methodologies/Project Management:**
   - Agile (iterative development, feature-by-feature)

2. **Coding Practices:**
   - OOP (Object-Oriented Programming)
   - MVC (Django's Model-View-Template pattern)
   - Test-Driven development for critical paths

3. **Programming Languages/Frameworks:**
   - Python 3.13
   - Django 5.x
   - MySQL 8 (with stored procedures)
   - Bootstrap 5 (via `crispy-bootstrap5`)
   - HTML / CSS / JavaScript

## Features

- **Patient portal** — register with SA ID, book/reschedule/cancel appointments, view follow-ups and prescriptions
- **Staff portal** — role-based access for doctors, nurses, receptionists, and admins
- **Clinical workflow** — medical records, clinical notes, referrals, prescriptions, follow-ups
- **Queue management** — check patients in, track waiting / in-progress / completed
- **Doctor scheduling** — block/unblock slots, whole-day blocks, date ranges
- **Reports** — appointment, patient activity, and weekly summary dashboards
- **Audit trail** — every create/update/delete is logged
- **OTP login** — SA ID or staff ID + SMS OTP for authentication
- **Public holiday awareness** — South African public holidays are respected when booking

## Setup

### Prerequisites

- Python 3.12+
- MySQL 8 (or MariaDB 10.5+)
- pip

### 1. Clone the repository

```sh
git clone https://github.com/iammelvink/NPRT63.git --depth=1
cd NPRT63/Code