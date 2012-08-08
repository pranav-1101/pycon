from django.conf.urls.defaults import patterns, url, include


urlpatterns = patterns("symposion.reviews.views",
    url(r"^$", "review_list", name="review_list"),
    url(r"^section/(?P<section_slug>[\w\-]+)/$", "review_section", name="review_section"),
    url(r"^section/(?P<section_slug>[\w\-]+)/assignments/$", "review_section", {"assigned": True}, name="review_section_assignments"),
    url(r"^section/(?P<section_slug>[\w\-]+)/stats/$", "review_stats", name="review_stats"),
    url(r"^section/(?P<section_slug>[\w\-]+)/stats/(?P<key>[\w]+)/$", "review_stats", name="review_stats"),
    
    
    url(r"^review/(?P<pk>\d+)/$", "review_detail", name="review_detail"),
    
    url(r"^list/(?P<username>[\w\-]+)/$", "review_list", name="review_list_user"),
    url(r"^admin/$", "review_admin", name="review_admin"),
    url(r"^admin/accept/$", "review_bulk_accept", name="review_bulk_accept"),
    url(r"^(?P<pk>\d+)/delete/$", "review_delete", name="review_delete"),
    url(r"^assignments/$", "review_assignments", name="review_assignments"),
    url(r"^assignment/(?P<pk>\d+)/opt-out/$", "review_assignment_opt_out", name="review_assignment_opt_out"),
)
