# Narrative spot check

Prompt `v3`, model `claude-sonnet-5-5`. 77 narratives: 53 passed first time, 13 passed after one regeneration, 11 need review.

The fidelity check is generation QA (the same model listing clinical content not in the facts), not ground truth.

## Needs review (11)

### 20278088 / metformin (test, needs_review)

**Answer key:** route `expedited_15_day`, due `2022-01-18`; serious `True` (other_medically_important)

| reaction | expectedness | decided by |
|---|---|---|
| Tachycardia | unexpected | human |
| Vomiting | expected | matcher |
| Diarrhoea | expected | matcher |

**Reporter:** consumer or other non-health professional → a family member of the patient, email from patient or family, target 161 words, actual 167

**Facts given:** `{"patient": {"age": "73 years", "sex": "female"}, "drug": {"name": "metformin hydrochloride extended-release tablets", "taken_for": "Diabetes mellitus", "dose": "500 MILLIGRAM"}, "other_suspect_drugs": [], "reactions": [{"event": "Tachycardia"}, {"event": "Vomiting"}, {"event": "Diarrhoea"}], "what_happened": ["the reporter assessed this event as medically significant"], "reporter_country": "IT"}`

> Source: email from patient or family  
> Received: 2022-01-03T15:36:52+00:00  
> Ref: INBOX-2022-30092
>
> Hello,
>
> I'm writing about my mother, who is 73. She takes metformin hydrochloride extended-release tablets, 500 mg, for her diabetes. I don't know exactly when she started them or how long she has been on them.
>
> Recently she has had a racing heartbeat, as if her heart is pounding much faster than it should, even when she is just sitting down. She has also been throwing up, and she has had a lot of loose, watery stools. I'm not sure exactly how many days this has been going on, maybe a few, and it seems to come and go.
>
> I'm quite worried about her. Personally I'd consider this a medically significant event, which is why I'm contacting you rather than waiting to see if it settles.
>
> I can send more details if you need them, but I'll have to be quick. My dog needs walking soon and he's already waiting by the door.
>
> Please let me know what else you need from me.
>
> Thank you,
> Giulia Rossi

**Flags on the kept version:**
- fidelity [symptom_or_sign]: "even when she is just sitting down" (The facts only list tachycardia. They do not say the racing heart occurred at rest, so this is an added clinical detail.)

**First attempt was flagged for:** "even when she is just sitting in her chair"

### 20278260 / levothyroxine (test, needs_review)

**Answer key:** route `periodic`; serious `False` (no criteria)

| reaction | expectedness | decided by |
|---|---|---|
| Lactose intolerance | ambiguous | undecided_partial_non_serious |

**Reporter:** pharmacist → pharmacist, professional email from HCP, target 151 words, actual 176

**Facts given:** `{"patient": {"sex": "male"}, "drug": {"name": "Levothyroxine Sodium", "taken_for": "Hypothyroidism", "dose": "1 DOSAGE FORM, QD", "started": "201906"}, "other_suspect_drugs": [], "reactions": [{"event": "Lactose intolerance", "outcome": "not recovered/not resolved"}], "what_happened": [], "reporter_country": "US"}`

> Source: professional email from HCP  
> Received: 2022-01-03T14:27:14+00:00  
> Ref: HCP-EM-2022-49849
>
> Subject lines are not needed, so I'll go straight to the body.
>
> Hello,
>
> I'm a pharmacist writing to report a case involving one of my male patients who takes Levothyroxine Sodium for hypothyroidism. He has been on it once a day, one dosage form each time, since about June 2019.
>
> He came to the counter recently and told me that dairy no longer agrees with him. He gets stomach upset after milk, cheese and similar foods, which he never had trouble with before. It appears he has become lactose intolerant. As far as I know, it hasn't cleared up and he is still dealing with it.
>
> I don't have any other details on his condition, and he isn't taking any other medicines that I'm aware of. I can try to find out more at his next pick-up if that would help.
>
> Apologies if this reads a bit scattered. A neighbour is doing loud renovation work right now and it's hard to concentrate. Please get in touch if you need anything further.
>
> Kind regards,
> Patricia Coleman, pharmacist

**Flags on the kept version:**
- fidelity [symptom_or_sign]: "He gets stomach upset after milk, cheese and similar foods, which he never had trouble with before." (Facts only list lactose intolerance; specific symptom of stomach upset after dairy and prior tolerance are not given.)

**First attempt was flagged for:** "dairy now upsets his stomach in a way it never used to"

### 20281949 / sertraline (dev, needs_review)

**Answer key:** route `expedited_15_day`, due `2022-01-18`; serious `True` (hospitalization)

| reaction | expectedness | decided by |
|---|---|---|
| Pre-eclampsia | unexpected | human |

**Reporter:** physician → doctor, partner safety report, target 99 words, actual 113

**Facts given:** `{"patient": {"age": "31 years", "sex": "female"}, "drug": {"name": "Sertraline Hcl", "taken_for": "Mixed anxiety and depressive disorder", "dose": "50 MILLIGRAM, QD", "started": "20210721"}, "other_suspect_drugs": [{"name": "Chlorpromazine", "taken_for": "Mixed anxiety and depressive disorder", "dose": "25 MILLIGRAM, QD", "started": "20210721"}, {"name": "Oxazepam", "taken_for": "Mixed anxiety and depressive disorder", "started": "20210709"}], "reactions": [{"event": "Pre-eclampsia", "outcome": "recovered/resolved"}], "what_happened": ["the patient was admitted to hospital"], "reporter_country": "FR"}`

> Source: partner safety report  
> Received: 2022-01-03T07:47:10+00:00  
> Ref: PSR-2022-44402
>
> Hello,
>
> Forwarding a report from our partner network, passed on by a doctor who did not give a name. A 31-year-old woman was taking Sertraline Hcl 50 mg daily for mixed anxiety and low mood, started 21 July 2021. She was also on chlorpromazine 25 mg daily from the same date, and oxazepam from 9 July 2021, dose not known. She developed high blood pressure in pregnancy with the kidney-related complications the doctor described as pre-eclampsia, and was admitted to hospital. She has since recovered fully. The doctor mentioned they are moving house next month, so follow-up may be slow. Reporter is in France.
>
> Regards,
> Sophie Bernard, Drug Safety Associate, Quarry Hill Health

**Flags on the kept version:**
- fidelity [symptom_or_sign]: "high blood pressure in pregnancy with the kidney-related complications" (Facts only list pre-eclampsia; the narrative adds hypertension and kidney-related complications as specific clinical features that are not given.)

**First attempt was flagged for:** "with raised blood pressure in pregnancy"

### 20282194 / metformin (test, needs_review)

**Answer key:** route `periodic`; serious `False` (no criteria)

| reaction | expectedness | decided by |
|---|---|---|
| Flatulence | expected | matcher |
| Dyspepsia | unexpected | matcher |
| Wrong technique in product usage process | excluded | matcher |

**Reporter:** consumer or other non-health professional → the patient, call-centre voicemail transcript, target 140 words, actual 141

**Facts given:** `{"patient": {"sex": "male"}, "drug": {"name": "metformin", "taken_for": "Glucose tolerance impaired", "started": "2018"}, "other_suspect_drugs": [], "reactions": [{"event": "Flatulence"}, {"event": "Dyspepsia"}, {"event": "Wrong technique in product usage process"}], "what_happened": [], "reporter_country": "US"}`

> Source: call-centre voicemail transcript  
> Received: 2022-01-03T07:33:44+00:00  
> Ref: CC-VM-2022-24818
>
> Hi, I'm calling to report a problem with my metformin. I just got back from holiday yesterday, so sorry if I'm a bit scattered. I've been on metformin since 2018. The doctor put me on it because my glucose tolerance was impaired. Lately I've had a lot of gas, more than I'd normally expect, and it's pretty embarrassing. I've also had a lot of indigestion, like a burning, upset feeling in my stomach after I eat. While I was away I got to thinking about how I take it, and I don't think I've been taking it the right way. I'm honestly not sure how long that's been going on. I'm in the US. I'd like someone to look into this and tell me what I should do. I can be reached on the number I'm calling from. Okay, thanks. Bye.

**Flags on the kept version:**
- fidelity [symptom_or_sign]: "like a burning, upset feeling in my stomach after I eat" (The facts only list dyspepsia. The burning sensation and the link to eating are new detail, beyond a lay description of indigestion.)

**First attempt was flagged for:** "I'm a man in my fifties"; "I never really had stomach trouble before this."; "Lately I've had a lot of gas, way more than usual"

### 20286485 / sertraline (test, needs_review)

**Answer key:** route `periodic`; serious `False` (no criteria)

| reaction | expectedness | decided by |
|---|---|---|
| Urticaria | expected | matcher |
| Product substitution issue | excluded | matcher |

**Reporter:** consumer or other non-health professional → the patient, call-centre voicemail transcript, target 168 words, actual 180

**Facts given:** `{"patient": {"sex": "female"}, "drug": {"name": "Zoloft", "dose": "STRENGTH: 100MG"}, "other_suspect_drugs": [], "reactions": [{"event": "Urticaria"}, {"event": "Product substitution issue"}], "what_happened": [], "reporter_country": "US"}`

> Source: call-centre voicemail transcript  
> Received: 2022-01-03T07:00:56+00:00  
> Ref: CC-VM-2022-93093
>
> Hi, I'm calling to report a problem with my medication. I take Zoloft, the 100 milligram tablets. Lately I've come out in hives, those itchy raised welts on my skin. I'm a woman, and I'm calling for myself.
>
> I think it might be connected to the pharmacy swapping my pills. At my last refill they handed me something different from what I normally get, not the Zoloft I'm used to. I didn't notice until I was home and looking at the bottle. I'm not sure exactly when the hives started compared to that, maybe around the same time, but I honestly can't say for certain.
>
> I'm sorry if this is rambling. I'm calling between sessions of my evening class, so I only have a few minutes, and I wanted to get it reported before I forgot.
>
> I don't have much more information right now. If you need details like the lot number or the pharmacy, I can look at the bottle and give them to you when someone calls me back. Okay, I'd better get back to class. Thanks, bye.

**Flags on the kept version:**
- fidelity [symptom_or_sign]: "those itchy raised welts on my skin" (Adds itching, which is not in the facts. Hives (urticaria) is supported, but the specific description of itchiness is a new symptom.)

**First attempt was flagged for:** "itchy raised welts"; "I take this every day."

### 20288831 / metformin (test, needs_review)

**Answer key:** route `expedited_15_day`, due `2022-01-19`; serious `True` (hospitalization, other_medically_important)

| reaction | expectedness | decided by |
|---|---|---|
| Toxic encephalopathy | unexpected | human |
| Azotaemia | unexpected | human |
| Metabolic acidosis | ambiguous | human |

**Reporter:** other health professional → nurse practitioner, professional email from HCP, target 170 words, actual 184

**Facts given:** `{"patient": {"age": "57 years", "sex": "male"}, "drug": {"name": "Metformin Hydrochloride Er", "taken_for": "Diabetes mellitus"}, "other_suspect_drugs": [], "reactions": [{"event": "Toxic encephalopathy", "outcome": "recovered/resolved"}, {"event": "Azotaemia", "outcome": "recovered/resolved"}, {"event": "Metabolic acidosis", "outcome": "recovered/resolved"}], "what_happened": ["the patient was admitted to hospital", "the reporter assessed this event as medically significant"], "reporter_country": "JP"}`

> Source: professional email from HCP  
> Received: 2022-01-04T08:56:24+00:00  
> Ref: HCP-EM-2022-78642
>
> Dear Drug Safety Team,
>
> I'm writing late at night after finishing a long shift, so please forgive any untidiness. I want to report a case involving a 57-year-old male patient of mine who was taking Metformin Hydrochloride Er for diabetes mellitus.
>
> He developed a confused, clouded mental state that appeared to be caused by a toxic process affecting the brain. His bloodwork also showed raised nitrogenous waste products, consistent with impaired kidney clearance, and he had a build-up of acid in the blood. He was admitted to hospital as a result.
>
> I would consider this a significant event, which is why I am contacting you rather than waiting. I am glad to say that all three problems have since cleared up and he has recovered.
>
> I do not have further details to hand regarding dose or how long he had been on the medication. No other suspect drugs have been identified on my side. If you need anything more for your records, please let me know and I will check the chart when I'm back in the clinic.
>
> Kind regards,
>
> Yuki Suzuki, nurse practitioner

**Flags on the kept version:**
- fidelity [symptom_or_sign]: "He developed a confused, clouded mental state" (Confusion/clouded mental state is a specific symptom not stated in the facts; the facts only name toxic encephalopathy, so this is a lay description of the same event and should be judged as borderline.)
- fidelity [diagnosis]: "consistent with impaired kidney clearance" (Impaired kidney clearance/renal impairment is an added interpretation not in the facts (azotaemia only).)
- fidelity [test_or_lab]: "His bloodwork also showed raised nitrogenous waste products" (Bloodwork/lab testing is not mentioned in the facts, though it describes azotaemia.)

**First attempt was flagged for:** "He developed a confused, foggy mental state"; "His bloodwork also showed a build-up of nitrogenous waste products, consistent with impaired kidney clearance"

### 20296644 / sertraline (dev, needs_review)

**Answer key:** route `expedited_15_day`, due `2022-01-20`; serious `True` (hospitalization, other_medically_important)

| reaction | expectedness | decided by |
|---|---|---|
| Haemorrhagic hepatic cyst | unexpected | human |
| Abdominal pain upper | unexpected | human |
| Abdominal pain | expected | matcher |

**Reporter:** pharmacist → pharmacist, professional email from HCP, target 89 words, actual 94

**Facts given:** `{"patient": {"age": "31 years", "sex": "male"}, "drug": {"name": "Sertraline Hcl", "dose": "100 MG, 1-0-0-0, TABLETS"}, "other_suspect_drugs": [], "reactions": [{"event": "Haemorrhagic hepatic cyst"}, {"event": "Abdominal pain upper"}, {"event": "Abdominal pain"}], "what_happened": ["the patient was admitted to hospital", "the reporter assessed this event as medically significant"], "reporter_country": "DE"}`

> Source: professional email from HCP  
> Received: 2022-01-05T18:39:30+00:00  
> Ref: HCP-EM-2022-27441
>
> Dear Drug Safety Team,
>
> I'm writing about a 31-year-old male patient of mine who takes Sertraline Hcl, 100 mg tablets, one in the morning. He came to the pharmacy complaining of pain in the upper abdomen and more general belly pain. He was later admitted to hospital, where they found a cyst in his liver that had bled. I would consider this a significant event. I'm sorry for the brief note, as my train was cancelled earlier and I'm writing in a hurry. I don't know the start date.
>
> Kind regards,
> Thomas Weber, pharmacist

**Flags on the kept version:**
- fidelity [care_detail]: "He came to the pharmacy complaining of pain in the upper abdomen and more general belly pain." (The facts list the abdominal pain reactions but do not say the patient presented at a pharmacy; this is new care detail.)

**First attempt was flagged for:** "I understand imaging then showed a cyst in the liver that had bled."

### 20297831 / lisinopril (test, needs_review)

**Answer key:** route `periodic`; serious `False` (no criteria)

| reaction | expectedness | decided by |
|---|---|---|
| Cough | expected | matcher |

**Reporter:** consumer or other non-health professional → a family member of the patient, call-centre voicemail transcript, target 149 words, actual 162

**Facts given:** `{"patient": {"age": "42 years", "sex": "female"}, "drug": {"name": "Zestril", "started": "202002"}, "other_suspect_drugs": [], "reactions": [{"event": "Cough", "outcome": "recovering/resolving"}], "what_happened": [], "reporter_country": "US"}`

> Source: call-centre voicemail transcript  
> Received: 2022-01-05T07:06:49+00:00  
> Ref: CC-VM-2022-38924
>
> Hi, this is Rachel Coleman calling from the US. I'm leaving a message because I want to report something about my sister. She's 42 and she's been taking Zestril since around February of 2020. She's had a cough, a dry, nagging kind of cough that just hangs around. It's been bothering her for a while now. The good news is it seems to be getting a bit better lately, so it's easing off, but it hasn't completely gone away yet.
>
> I'm not sure what else you need from me. I don't have the lot number or anything like that in front of me. I'm about to head out for a night shift, so I can't talk long, and I'll be hard to reach tonight. If you need more details, please leave me a message with a number and a good time to call back, and I'll get back to you tomorrow when I'm up.
>
> Okay, thank you very much. Bye.
>
> Rachel Coleman

**Flags on the kept version:**
- fidelity [symptom_or_sign]: "a dry, nagging kind of cough" (The facts say only 'Cough'; describing it as dry is a new clinical characteristic not in the facts.)

**First attempt was flagged for:** "dry, hacking cough, the kind that tickles the back of her throat and just won't quit"

### 20298221 / warfarin (test, needs_review)

**Answer key:** route `expedited_15_day`, due `2022-01-19`; serious `True` (hospitalization)

| reaction | expectedness | decided by |
|---|---|---|
| Transient ischaemic attack | unexpected | human |
| Cerebrovascular accident | unexpected | human |
| Anticoagulation drug level below therapeutic | excluded | human |

**Reporter:** pharmacist → pharmacist, professional email from HCP, target 151 words, actual 168

**Facts given:** `{"patient": {"age": "49 years", "sex": "female"}, "drug": {"name": "warfarin", "taken_for": "Atrial fibrillation", "started": "20200428"}, "other_suspect_drugs": [], "reactions": [{"event": "Transient ischaemic attack"}, {"event": "Cerebrovascular accident"}, {"event": "Anticoagulation drug level below therapeutic"}], "what_happened": ["the patient was admitted to hospital"], "reporter_country": "US"}`

> Source: professional email from HCP  
> Received: 2022-01-04T13:21:22+00:00  
> Ref: HCP-EM-2022-72751
>
> Hello,
>
> I'm writing to report an adverse event involving a female patient of mine, aged 49, who has been taking warfarin for atrial fibrillation. As far as I can tell from our records, she started it on 28 April 2020. She is not on any other medication that I know of.
>
> She recently experienced what appears to have been a transient ischaemic attack, a brief "mini-stroke" episode, and she has also had a full stroke. Her anticoagulation levels were found to be below the therapeutic range. She was admitted to hospital. I don't have the exact dates of these events, and I don't know how she is doing now.
>
> I can look into our dispensing records if you need further details. Please bear with me on timing, as I'll be away from my desk a little on Friday. My grandchild's birthday party is this weekend and we're getting ready for it.
>
> Please let me know if you need anything else for your report.
>
> Kind regards,
> David Coleman, pharmacist

**Flags on the kept version:**
- fidelity [other_drug]: "She is not on any other medication that I know of." (The facts list no other suspect drugs but say nothing about her concomitant medications, so this statement about her other medication is not supported.)

**First attempt was flagged for:** "which her physicians were treating as a transient ischaemic attack"

### 20305864 / levothyroxine (test, needs_review)

**Answer key:** route `periodic`; serious `False` (no criteria)

| reaction | expectedness | decided by |
|---|---|---|
| Weight increased | ambiguous | undecided_partial_non_serious |

**Reporter:** consumer or other non-health professional → a family member of the patient, call-centre voicemail transcript, target 111 words, actual 121

**Facts given:** `{"patient": {"sex": "female"}, "drug": {"name": "Thyquidity", "taken_for": "Hypothyroidism", "dose": "88 MICROGRAM, QD"}, "other_suspect_drugs": [], "reactions": [{"event": "Weight increased"}], "what_happened": [], "reporter_country": "US"}`

> Source: call-centre voicemail transcript  
> Received: 2022-01-06T14:55:10+00:00  
> Ref: CC-VM-2022-29958
>
> Hi, this message is about my sister. My name is Ashley Sullivan. I'm calling from a borrowed laptop, since I'm using it to find your number, so sorry if I sound distracted. My sister takes Thyquidity for her underactive thyroid. As far as I know it's 88 micrograms, once a day. She's been putting on weight, and it's noticeable. Her clothes don't fit the way they did, and she says her eating hasn't changed. I'm not sure exactly when it started, maybe a while back. I don't have any other details with me right now. I just wanted to report it so it's on record. You can call me back on this number if you need anything else. Thanks. Ashley Sullivan

**Flags on the kept version:**
- fidelity [other]: "she says her eating hasn't changed" (Reports unchanged dietary intake, a clinical history detail that is not in the facts.)

**First attempt was flagged for:** "she's been taking the Thyquidity the whole time"

### 20327766 / atorvastatin (test, needs_review)

**Answer key:** route `periodic`; serious `False` (no criteria)

| reaction | expectedness | decided by |
|---|---|---|
| Headache | unexpected | matcher |

**Reporter:** consumer or other non-health professional → the patient, call-centre voicemail transcript, target 116 words, actual 116

**Facts given:** `{"patient": {"age": "71 years", "sex": "female"}, "drug": {"name": "Atorvastatin Calcium", "dose": "20 MG, DAILY (QUANTITY DISPENSED 90 DAYS SUPPLY 90)"}, "other_suspect_drugs": [], "reactions": [{"event": "Headache"}], "what_happened": [], "reporter_country": "US"}`

> Source: call-centre voicemail transcript  
> Received: 2022-01-12T11:36:33+00:00  
> Ref: CC-VM-2022-36226
>
> Hi, I'm calling to report a problem with my medication. Sorry about the background noise, I'm in a café at the moment. I'm a 71-year-old woman, and I take Atorvastatin Calcium, 20 milligrams once a day. The pharmacy gave me a 90-day supply, so ninety tablets in one go. I've been getting these headaches, a sort of pounding ache in my head that keeps coming back. I can't say exactly when it started, I just noticed it was happening and wanted to tell someone. I'm in the US. I'd like somebody from your drug safety department to note this down and call me back if they need more details from me. Okay, thank you. Bye now.

**Flags on the kept version:**
- fidelity [symptom_or_sign]: "a sort of pounding ache in my head that keeps coming back" (The facts only say headache. Describing it as pounding and recurring adds character and a pattern that the facts do not give.)

**First attempt was flagged for:** "They're just a sore, pounding head"; "I don't usually get headaches like this"

## Random passed sample (10: 5 dev, 5 test)

### 20279004 / metformin (dev, passed)

**Answer key:** route `expedited_15_day`, due `2022-01-18`; serious `True` (other_medically_important)

| reaction | expectedness | decided by |
|---|---|---|
| Muscle spasms | unexpected | human |
| Vitamin B6 deficiency | unexpected | human |

**Reporter:** other health professional → physician assistant, partner safety report, target 93 words, actual 106

**Facts given:** `{"patient": {"age": "59 years", "sex": "female"}, "drug": {"name": "metformin er 750 mg", "taken_for": "Type 2 diabetes mellitus"}, "other_suspect_drugs": [], "reactions": [{"event": "Muscle spasms", "outcome": "recovered/resolved"}, {"event": "Vitamin B6 deficiency", "outcome": "recovered/resolved"}], "what_happened": ["the reporter assessed this event as medically significant"], "reporter_country": "US"}`

> Source: partner safety report  
> Received: 2022-01-03T08:11:20+00:00  
> Ref: PSR-2022-56545
>
> Hello,
>
> Passing along a report from a physician assistant in the US, who did not give their name. They treated a 59-year-old woman taking metformin er 750 mg for type 2 diabetes. She developed muscle spasms and was also found to have low vitamin B6 (pyridoxine). Both problems have since resolved. The physician assistant told us they consider this a medically significant event. No other suspect drugs were reported, and I have no dates or further details yet.
>
> Apologies if this is thinner than usual, as the kids are off school for the holiday and I'm working around them.
>
> Keisha Ramirez, Drug Safety Associate, Ferncliff Medical

### 20289118 / levothyroxine (dev, passed)

**Answer key:** route `expedited_15_day`, due `2022-01-19`; serious `True` (other_medically_important)

| reaction | expectedness | decided by |
|---|---|---|
| Dialysis | unexpected | human |
| Alopecia | expected | human |

**Reporter:** consumer or other non-health professional → a family member of the patient, call-centre voicemail transcript, target 147 words, actual 159

**Facts given:** `{"patient": {"sex": "female"}, "drug": {"name": "levothyroxine sodium", "taken_for": "Hypothyroidism"}, "other_suspect_drugs": [], "reactions": [{"event": "Dialysis"}, {"event": "Alopecia"}], "what_happened": ["the reporter assessed this event as medically significant"], "reporter_country": "COUNTRY NOT SPECIFIED"}`

> Source: call-centre voicemail transcript  
> Received: 2022-01-04T09:03:38+00:00  
> Ref: CC-VM-2022-90293
>
> Hello, this is a message for your drug safety team. I'm calling about my mother. She takes levothyroxine sodium for her underactive thyroid. Sorry if there's noise, I've got the back door open because the garden is completely flooded after all that heavy rain, and I'm trying to sort that out while I call.
>
> Anyway, my mother has ended up needing dialysis, and her hair has been falling out too, quite a lot of it, in clumps on her pillow and in the brush. I'm not sure exactly when either of these started, and I don't know the dose she's on. She isn't taking any other medicines that I know of.
>
> I'd consider this a significant event, particularly the dialysis, and I wanted it on record with you. I'm worried about her.
>
> If someone could ring me back on this number, I can give you more details, or tell you what I do know. Thank you. It's Nina Costa.

### 20282292 / warfarin (dev, passed)

**Answer key:** route `expedited_15_day`, due `2022-01-16`; serious `True` (hospitalization)

| reaction | expectedness | decided by |
|---|---|---|
| Haemorrhage | expected | matcher |
| Transfusion | unexpected | human |

**Reporter:** pharmacist → pharmacist, partner safety report, target 82 words, actual 95

**Facts given:** `{"patient": {"age": "74 years", "sex": "male"}, "drug": {"name": "warfarin"}, "other_suspect_drugs": [], "reactions": [{"event": "Haemorrhage"}, {"event": "Transfusion"}], "what_happened": ["the patient was admitted to hospital"], "reporter_country": "US"}`

> Source: partner safety report  
> Received: 2022-01-01T18:26:44+00:00  
> Ref: PSR-2022-14146
>
> Hello,
>
> Passing on a report received today from a pharmacist in the US. They contacted us while waiting at home for a plumber to arrive. The pharmacist described a 74-year-old man taking warfarin who had a bleed. He was admitted to hospital and needed a blood transfusion. The pharmacist did not have the dose, start date, or the site of the bleeding. No other medicines were mentioned as suspects. They did not give their name.
>
> Please let me know if you need us to request follow-up information.
>
> Regards,
> Darnell Patel, Drug Safety Associate, Altavia Health

### 20300287 / atorvastatin (dev, passed)

**Answer key:** route `periodic`; serious `True` (other_medically_important)

| reaction | expectedness | decided by |
|---|---|---|
| Liver injury | expected | human |
| Off label use | excluded | matcher |

**Reporter:** consumer or other non-health professional → the patient, call-centre voicemail transcript, target 168 words, actual 173

**Facts given:** `{"patient": {"age": "77 years", "sex": "female"}, "drug": {"name": "atorvastatin calcium", "taken_for": "Hypertension", "dose": "20 MG, 1X/DAY", "started": "20211121"}, "other_suspect_drugs": [], "reactions": [{"event": "Liver injury", "outcome": "recovering/resolving"}, {"event": "Off label use", "outcome": "recovered/resolved"}], "what_happened": ["the reporter assessed this event as medically significant"], "reporter_country": "CN"}`

> Source: call-centre voicemail transcript  
> Received: 2022-01-05T16:27:33+00:00  
> Ref: CC-VM-2022-18119
>
> Hello, I'm calling to report a problem with a medicine, and I'm on a slow train, so the signal keeps dropping. If I cut out, I'm sorry. I'm a 77-year-old woman, and I take atorvastatin calcium, 20 milligrams, one tablet a day. I started it around the 21st of November 2021. It was prescribed for my high blood pressure, which I understand isn't the usual reason people are given it. Anyway, I've had damage to my liver. It's what I was told, that the liver was injured. I'd say that's a significant medical event for me, and I wanted it on record. I'm getting better now, slowly. It's improving, but it isn't completely gone yet. I can't remember all the details at the moment, and I don't have my paperwork with me. I'm not sure what else you need from me. Sorry, I think we're going into a tunnel... Please ring me back on this number if you need more information, and I'll try to answer when the signal's better. Thank you. Bye.

### 20318896 / warfarin (dev, passed)

**Answer key:** route `periodic`; serious `False` (no criteria)

| reaction | expectedness | decided by |
|---|---|---|
| Injection site bruising | unexpected | matcher |
| Rash | expected | matcher |
| Skin discolouration | unexpected | matcher |

**Reporter:** consumer or other non-health professional → a family member of the patient, email from patient or family, target 127 words, actual 121

**Facts given:** `{"patient": {"sex": "female"}, "drug": {"name": "Warfarin Sodium"}, "other_suspect_drugs": [{"name": "Cosentyx", "taken_for": "Psoriatic arthropathy", "dose": "150 MG, QW", "started": "202111"}], "reactions": [{"event": "Injection site bruising"}, {"event": "Rash", "outcome": "recovered/resolved"}, {"event": "Skin discolouration", "outcome": "recovering/resolving"}], "what_happened": [], "reporter_country": "US"}`

> Source: email from patient or family  
> Received: 2022-01-10T08:47:02+00:00  
> Ref: INBOX-2022-78951
>
> Hello,
>
> I'm writing about my mother, who takes Warfarin Sodium. She also uses Cosentyx for her psoriatic arthritis, 150 mg once a week, and she started that around November 2021. I'm not sure of the warfarin dose or when she began it.
>
> She has been getting bruises where she does the Cosentyx injection. She also had a rash, which has cleared up now. The skin in that area is still discoloured, though it seems to be fading slowly.
>
> I tried to report this through your website but the internet at home keeps dropping, so I gave up and am emailing instead. Sorry if anything is unclear. I can try to answer questions if you need more details.
>
> Thank you,
> Maria Patel

### 20282093 / sertraline (test, passed)

**Answer key:** route `expedited_15_day`, due `2022-01-18`; serious `True` (hospitalization)

| reaction | expectedness | decided by |
|---|---|---|
| Intestinal obstruction | unexpected | human |

**Reporter:** physician → doctor, partner safety report, target 129 words, actual 148

**Facts given:** `{"patient": {"age": "1 days", "sex": "male"}, "drug": {"name": "Sertraline Hcl", "taken_for": "Mixed anxiety and depressive disorder", "dose": "50 MILLIGRAM, QD", "started": "20210721"}, "other_suspect_drugs": [{"name": "Chlorpromazine", "taken_for": "Mixed anxiety and depressive disorder", "dose": "25 MILLIGRAM, QD", "started": "20210721"}, {"name": "Oxazepam", "taken_for": "Mixed anxiety and depressive disorder", "started": "20210709"}], "reactions": [{"event": "Intestinal obstruction", "outcome": "recovered/resolved"}], "what_happened": ["the patient was admitted to hospital"], "reporter_country": "FR"}`

> Source: partner safety report  
> Received: 2022-01-03T08:56:27+00:00  
> Ref: PSR-2022-25780
>
> Hello,
>
> We are forwarding a report received by phone from a doctor in France, who did not give their name. The doctor mentioned in passing that they had just got a new puppy and were short on sleep, but was keen to get this reported.
>
> The patient is a baby boy, one day old. He was admitted to hospital with a blockage of the bowel. The doctor described it as an obstruction of the intestine. He has since recovered and the problem has resolved.
>
> Medicines given for mixed anxiety and depressive disorder:
> - Sertraline Hcl, 50 mg once daily, started 21 July 2021
> - Chlorpromazine, 25 mg once daily, started 21 July 2021
> - Oxazepam, started 9 July 2021, dose not known
>
> How the baby was exposed to these medicines was not stated, and no other details were provided.
>
> Kind regards,
>
> Sophie Moreau
> Drug Safety Associate
> Solenne Laboratories

### 20280044 / metformin (test, passed)

**Answer key:** route `expedited_15_day`, due `2022-01-18`; serious `True` (hospitalization)

| reaction | expectedness | decided by |
|---|---|---|
| Groin abscess | unexpected | human |
| Product monitoring error | unexpected | human |

**Reporter:** pharmacist → pharmacist, partner safety report, target 89 words, actual 93

**Facts given:** `{"patient": {"age": "64 years", "sex": "male"}, "drug": {"name": "metformin", "dose": "500 MILLIGRAM, 1-0-1-1"}, "other_suspect_drugs": [{"name": "Allopurinol", "dose": "300 MILLIGRAM, 0-0.5-0-0"}, {"name": "Sitagliptin", "dose": "100 MILLIGRAM, 1-0-0-0"}], "reactions": [{"event": "Groin abscess"}, {"event": "Product monitoring error"}], "what_happened": ["the patient was admitted to hospital"], "reporter_country": "DE"}`

> Source: partner safety report  
> Received: 2022-01-03T18:56:22+00:00  
> Ref: PSR-2022-26921
>
> Hello,
>
> We received a report from a pharmacist in Germany, who gave no name, about a man of 64 on metformin 500 mg, taken 1-0-1-1. He also takes allopurinol 300 mg (0-0.5-0-0) and sitagliptin 100 mg (1-0-0-0). He developed an abscess in his groin and was admitted to hospital. The pharmacist also mentioned a monitoring mistake involving the product, with no further detail. The pharmacist was delayed getting the information to us because the hospital car park was full. No other details are available.
>
> Regards,
> Stefan Weber, Drug Safety Associate, Arkhaven Life Sciences

### 20324413 / atorvastatin (test, passed_after_regeneration)

**Answer key:** route `periodic`; serious `False` (no criteria)

| reaction | expectedness | decided by |
|---|---|---|
| Muscular weakness | ambiguous | undecided_partial_non_serious |

**Reporter:** consumer or other non-health professional → the patient, email from patient or family, target 121 words, actual 144

**Facts given:** `{"patient": {"age": "69 years", "sex": "male"}, "drug": {"name": "atorvastatin calcium, film coated"}, "other_suspect_drugs": [], "reactions": [{"event": "Muscular weakness"}], "what_happened": [], "reporter_country": "US"}`

> Source: email from patient or family  
> Received: 2022-01-11T09:24:23+00:00  
> Ref: INBOX-2022-76434
>
> Hello,
>
> I'm writing because I've been taking atorvastatin calcium, film coated, and I think it may be causing a problem. I'm a 69-year-old man, and lately my muscles feel weak. It's hard to describe, but my arms and legs just don't have the strength they used to. Carrying groceries in from the car or getting up out of a low chair has become noticeably harder than it was.
>
> I can't say exactly when it began. Maybe a few weeks ago, but I'm guessing. I don't remember the dose off the top of my head, and I'd have to look at the bottle.
>
> I'm sending this from the waiting area at the garage, since the car is in for a service and I have some time. Please let me know if you need anything else from me, or how to report this properly.
>
> Thank you.

**First attempt was flagged for:** "my arms and legs just don't have the strength they used to"; "I get tired holding things I never used to think twice about."

### 20318323 / atorvastatin (test, passed_after_regeneration)

**Answer key:** route `periodic`; serious `False` (no criteria)

| reaction | expectedness | decided by |
|---|---|---|
| Aphasia | unexpected | matcher |
| Myalgia | expected | matcher |
| Hepatic enzyme increased | expected | matcher |

**Reporter:** physician → doctor, professional email from HCP, target 143 words, actual 147

**Facts given:** `{"patient": {"age": "64 years", "sex": "female"}, "drug": {"name": "atorvastatin calcium"}, "other_suspect_drugs": [{"name": "Aubagio", "taken_for": "Multiple sclerosis", "dose": "14 MG, QD", "started": "20210224"}], "reactions": [{"event": "Aphasia", "outcome": "not recovered/not resolved"}, {"event": "Myalgia", "outcome": "not recovered/not resolved"}, {"event": "Hepatic enzyme increased"}], "what_happened": [], "reporter_country": "US"}`

> Source: professional email from HCP  
> Received: 2022-01-10T09:55:32+00:00  
> Ref: HCP-EM-2022-60906
>
> Subject line omitted as requested, so here is the message:
>
> Hello Drug Safety Team,
>
> I'm writing to report a case involving a 64-year-old female patient of mine who has been taking atorvastatin calcium. She is also on Aubagio 14 mg once daily for multiple sclerosis, which she started on 24 February 2021.
>
> She has developed trouble finding and forming words, and she has muscle aches. Neither has gone away as of today. Her liver enzymes also came back raised. I don't have the dose or start date for the atorvastatin to hand, so I can't include those at the moment.
>
> I wanted to get this to you promptly. I would have faxed the chart notes, but my printer is jammed, so I can send them as scanned copies if that works for you.
>
> Please let me know what further information you need.
>
> Kind regards,
> Dr Keisha Johnson

**First attempt was flagged for:** "Her bloodwork has shown raised liver enzymes as well."

### 20362145 / levothyroxine (test, passed)

**Answer key:** route `periodic`; serious `False` (no criteria)

| reaction | expectedness | decided by |
|---|---|---|
| Drug hypersensitivity | ambiguous | undecided_partial_non_serious |
| Face oedema | unexpected | matcher |
| Oedema peripheral | unexpected | matcher |

**Reporter:** physician → doctor, professional email from HCP, target 151 words, actual 163

**Facts given:** `{"patient": {"age": "88 years", "sex": "female"}, "drug": {"name": "Tirosint Sol"}, "other_suspect_drugs": [], "reactions": [{"event": "Drug hypersensitivity"}, {"event": "Face oedema"}, {"event": "Oedema peripheral"}], "what_happened": [], "reporter_country": "US"}`

> Source: professional email from HCP  
> Received: 2022-01-21T12:42:12+00:00  
> Ref: HCP-EM-2022-35462
>
> Hello,
>
> I'm writing to report an adverse event involving one of my patients, an 88-year-old woman who has been taking Tirosint Sol. I don't have the start date or dose to hand, and I'm not certain of the indication from the notes I have in front of me.
>
> She came in looking puffy around the face, with noticeable swelling in her cheeks and around the eyes. Her ankles and lower legs were also swollen. Taken together, it looked to me like an allergic-type reaction to the medication, a hypersensitivity picture, though I haven't confirmed that.
>
> I'm sorry this report is a bit sparse. I was meant to send it yesterday, but my bike got a flat tyre on the ride in and the morning got away from me. I can pull more detail from her chart if that would help.
>
> Please let me know what additional information you need, and I will do my best to provide it.
>
> Kind regards,
>
> Dr Darnell Ramirez
