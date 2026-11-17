# Visual board component catalog

Every component has a unique `id`, a registered `type`, and a matching `data`
object. Send plain text only. The frontend never accepts HTML.

## Structure

```json
{
  "title": "Your day",
  "layout": "grid",
  "components": []
}
```

Layouts: `grid`, `columns`, `spotlight`.

## Components

### heading

```json
{"id":"overview","type":"heading","data":{"text":"Your day","subtitle":"Monday, 16 November","level":1}}
```

### rich_text

```json
{"id":"summary","type":"rich_text","data":{"title":"Summary","text":"Plain text with line breaks."}}
```

### metric_cards

```json
{"id":"counts","type":"metric_cards","data":{"items":[{"label":"Tasks","value":"6","detail":"2 high priority"}]}}
```

### list

```json
{"id":"items","type":"list","data":{"title":"Highlights","items":[{"title":"Item","subtitle":"Supporting detail","badge":"New"}]}}
```

### task_list

```json
{"id":"tasks","type":"task_list","data":{"title":"Today","tasks":[{"title":"Review proposal","project":"Personal","due":"11:00","status":"Todo"}]}}
```

### knowledge_list

```json
{"id":"notes","type":"knowledge_list","data":{"title":"Saved ideas","items":[{"title":"Kitchen layout","excerpt":"Keep the sink on the east wall","kind":"idea","tags":["home"],"updated":"Today"}]}}
```

### knowledge_detail

```json
{"id":"note","type":"knowledge_detail","data":{"title":"Kitchen dimensions","content":"The study wall is 3.2 metres wide.","kind":"note","tags":["home"],"source_url":null,"updated":"Today"}}
```

### email_list

```json
{"id":"mail","type":"email_list","data":{"title":"Important mail","messages":[{"sender":"Maya","subject":"Launch plan","preview":"The final review moved…","time":"09:42","unread":true}]}}
```

### email_detail

```json
{"id":"message","type":"email_detail","data":{"sender":"Maya","recipients":["Purujit"],"subject":"Launch plan","date":"Today, 09:42","body":"Plain-text message body."}}
```

### calendar_agenda

```json
{"id":"agenda","type":"calendar_agenda","data":{"title":"Today","date":"16 November","events":[{"time":"10:30","title":"Project review","duration":"45 min","location":"Meet"}]}}
```

### event_detail

```json
{"id":"event","type":"event_detail","data":{"title":"Project review","start":"10:30","end":"11:15","location":"Meet","attendees":["Maya"],"description":"Review launch readiness."}}
```

### timeline

```json
{"id":"timeline","type":"timeline","data":{"title":"Delivery","items":[{"time":"Monday","title":"Draft","description":"Initial version","status":"Done"}]}}
```

### table

```json
{"id":"comparison","type":"table","data":{"title":"Options","columns":["Name","Cost"],"rows":[["A","₹500"],["B","₹700"]]}}
```

### key_value

```json
{"id":"details","type":"key_value","data":{"title":"Details","items":[{"label":"Owner","value":"Purujit"}]}}
```

### chart

Kinds: `bar`, `line`, `donut`. Each series must contain values corresponding to
the labels.

```json
{"id":"trend","type":"chart","data":{"title":"Completed","kind":"bar","labels":["Mon","Tue"],"series":[{"name":"Tasks","values":[3,5]}]}}
```

### image

Only HTTPS images are suitable for the PWA.

```json
{"id":"image","type":"image","data":{"src":"https://example.com/image.jpg","alt":"Descriptive alternative text","caption":"Optional caption"}}
```

### callout

Tones: `info`, `success`, `warning`, `danger`.

```json
{"id":"notice","type":"callout","data":{"title":"Heads up","text":"One important observation.","tone":"info"}}
```

### loading

```json
{"id":"loading","type":"loading","data":{"text":"Gathering your calendar…"}}
```

### empty_state

```json
{"id":"empty","type":"empty_state","data":{"title":"Nothing scheduled","text":"Your afternoon is clear."}}
```
