from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User

from symposion.proposals.models import ProposalBase, ProposalSection
from symposion.reviews.forms import ReviewForm, ReviewCommentForm, SpeakerCommentForm
from symposion.reviews.forms import BulkPresentationForm
from symposion.reviews.models import ReviewAssignment, Review, LatestVote, VOTES
from symposion.utils.mail import send_email


def access_not_permitted(request):
    return render(request, "reviews/access_not_permitted.html")


def proposals_generator(request, queryset, username=None, check_speaker=True):
    for obj in queryset:
        # @@@ this sucks; we can do better
        if check_speaker:
            if request.user in [s.user for s in obj.speakers()]:
                continue
        if obj.result is None:
            continue
        obj.comment_count = obj.result.comment_count
        obj.total_votes = obj.result.vote_count
        obj.plus_one = obj.result.plus_one
        obj.plus_zero = obj.result.plus_zero
        obj.minus_zero = obj.result.minus_zero
        obj.minus_one = obj.result.minus_one
        lookup_params = dict(proposal=obj)
        if username:
            lookup_params["user__username"] = username
        else:
            lookup_params["user"] = request.user
        try:
            obj.latest_vote = LatestVote.objects.get(**lookup_params).css_class()
        except LatestVote.DoesNotExist:
            obj.latest_vote = "no-vote"
        yield obj


def group_proposals(proposals):
    grouped = {}
    for proposal in proposals:
        kind = proposal.kind
        if kind in grouped:
            grouped[kind].append(proposal)
        else:
            grouped[kind] = [proposal]
    return grouped


@login_required
def review_section(request, section_slug, assigned=False):
    
    if not request.user.has_perm("reviews.can_review_%s" % section_slug):
        return access_not_permitted(request)
    
    section = get_object_or_404(ProposalSection, section__slug=section_slug)
    queryset = ProposalBase.objects.filter(kind__section=section)
    
    if assigned:
        assignments = ReviewAssignment.objects.filter(user=request.user).values_list("proposal__id")
        queryset = queryset.filter(id__in=assignments)
    queryset = queryset.select_related("result").select_subclasses()
    proposals = proposals_generator(request, queryset)
    ctx = {
        "proposals": proposals,
    }
    return render(request, "reviews/review_list.html", ctx)


@login_required
def review_list(request, username=None):
    
    if username:
        # if they're not a reviewer admin and they aren't the person whose
        # review list is being asked for, don't let them in
        if not request.user.groups.filter(name="reviewers-admins").exists():
            if not request.user.username == username:
                return access_not_permitted(request)
    else:
        if not request.user.groups.filter(name="reviewers").exists():
            return access_not_permitted(request)
    
    queryset = ProposalBase.objects.select_related("speaker__user", "result")
    if username:
        reviewed = LatestVote.objects.filter(user__username=username).values_list("proposal", flat=True)
        queryset = queryset.filter(pk__in=reviewed)
    queryset = queryset.order_by("submitted")
    
    # filter out tutorials for now
    queryset = queryset.exclude(kind__name__iexact="tutorial")
    
    admin = request.user.groups.filter(name="reviewers-admins").exists()
    
    proposals = group_proposals(proposals_generator(request, queryset, username=username, check_speaker=not admin))
    rated_proposals = queryset.filter(reviews__user=request.user)

    ctx = {
        "proposals": proposals,
        "rated_proposals": rated_proposals,
        "username": username,
    }
    return render(request, "reviews/review_list.html", ctx)


@login_required
def review_admin(request):
    
    if not request.user.groups.filter(name="reviewers-admins").exists():
        return access_not_permitted(request)
    
    def reviewers():
        queryset = User.objects.distinct().filter(groups__name="reviewers")
        for obj in queryset:
            obj.comment_count = Review.objects.filter(user=obj).count()
            obj.total_votes = LatestVote.objects.filter(user=obj).count()
            obj.plus_one = LatestVote.objects.filter(
                user = obj,
                vote = LatestVote.VOTES.PLUS_ONE
            ).count()
            obj.plus_zero = LatestVote.objects.filter(
                user = obj,
                vote = LatestVote.VOTES.PLUS_ZERO
            ).count()
            obj.minus_zero = LatestVote.objects.filter(
                user = obj,
                vote = LatestVote.VOTES.MINUS_ZERO
            ).count()
            obj.minus_one = LatestVote.objects.filter(
                user = obj,
                vote = LatestVote.VOTES.MINUS_ONE
            ).count()
            yield obj
    ctx = {
        "reviewers": reviewers(),
    }
    return render(request, "reviews/review_admin.html", ctx)


@login_required
def review_detail(request, pk):
    
    proposals = ProposalBase.objects.select_related("result").select_subclasses()
    proposal = get_object_or_404(proposals, pk=pk)
    
    if not request.user.has_perm("reviews.can_review_%s" % proposal.kind.section.slug):
        return access_not_permitted(request)
    
    speakers = [s.user for s in proposal.speakers()]
    
    if not request.user.is_superuser and request.user in speakers:
        return access_not_permitted(request)
    
    admin = request.user.is_staff
    
    try:
        latest_vote = LatestVote.objects.get(proposal=proposal, user=request.user)
    except LatestVote.DoesNotExist:
        latest_vote = None
    
    if request.method == "POST":
        if request.user in speakers:
            return access_not_permitted(request)
        
        if "vote_submit" in request.POST:
            review_form = ReviewForm(request.POST)
            if review_form.is_valid():
                
                review = review_form.save(commit=False)
                review.user = request.user
                review.proposal = proposal
                review.save()
                
                return redirect(request.path)
            else:
                message_form = SpeakerCommentForm()
        elif "message_submit" in request.POST:
            message_form = SpeakerCommentForm(request.POST)
            if message_form.is_valid():
                
                message = message_form.save(commit=False)
                message.user = request.user
                message.proposal = proposal
                message.save()
                
                for speaker in speakers:
                    if speaker and speaker.email:
                        ctx = {
                            "proposal": proposal,
                            "message": message,
                            "reviewer": False,
                        }
                        send_email(
                            [speaker.email], "proposal_new_message",
                            context = ctx
                        )
                
                return redirect(request.path)
            else:
                initial = {}
                if latest_vote:
                    initial["vote"] = latest_vote.vote
                if request.user in speakers:
                    review_form = None
                else:
                    review_form = ReviewForm(initial=initial)
        elif "result_submit" in request.POST:
            if admin:
                result = request.POST["result_submit"]
                
                if result == "accept":
                    proposal.result.accepted = True
                    proposal.result.save()
                elif result == "reject":
                    proposal.result.accepted = False
                    proposal.result.save()
                elif result == "undecide":
                    proposal.result.accepted = None
                    proposal.result.save()
            
            return redirect(request.path)
    else:
        initial = {}
        if latest_vote:
            initial["vote"] = latest_vote.vote
        if request.user in speakers:
            review_form = None
        else:
            review_form = ReviewForm(initial=initial)
        message_form = SpeakerCommentForm()
    
    
    proposal.comment_count = proposal.result.comment_count
    proposal.total_votes = proposal.result.vote_count
    proposal.plus_one = proposal.result.plus_one
    proposal.plus_zero = proposal.result.plus_zero
    proposal.minus_zero = proposal.result.minus_zero
    proposal.minus_one = proposal.result.minus_one
    
    reviews = Review.objects.filter(proposal=proposal).order_by("-submitted_at")
    messages = proposal.messages.order_by("submitted_at")
    
    return render(request, "reviews/review_detail.html", {
        "proposal": proposal,
        "latest_vote": latest_vote,
        "reviews": reviews,
        "review_messages": messages,
        "review_form": review_form,
        "message_form": message_form
    })


@login_required
@require_POST
def review_delete(request, pk):
    if not request.user.groups.filter(name="reviewers-admins").exists():
        return access_not_permitted(request)
    review = get_object_or_404(Review, pk=pk)
    review.delete()
    return redirect("review_detail", pk=review.proposal.pk)


@login_required
def review_stats(request, section_slug=None, key=None):
    
    ctx = {
        "section_slug": section_slug
    }
    
    queryset = ProposalBase.objects.select_related("speaker__user", "result").select_subclasses()
    if section_slug:
        queryset = queryset.filter(kind__section__slug=section_slug)
    
    proposals = {
        # proposals with at least one +1 and no -1s, sorted by the 'score'
        "good": queryset.filter(result__plus_one__gt=0, result__minus_one=0).order_by("-result__score"),
        # proposals with at least one -1 and no +1s, reverse sorted by the 'score'
        "bad": queryset.filter(result__minus_one__gt=0, result__plus_one=0).order_by("result__score"),
        # proposals with neither a +1 or a -1, sorted by total votes (lowest first)
        "indifferent": queryset.filter(result__minus_one=0, result__plus_one=0).order_by("result__vote_count"),
        # proposals with both a +1 and -1, sorted by total votes (highest first)
        "controversial": queryset.filter(result__plus_one__gt=0, result__minus_one__gt=0).order_by("-result__vote_count"),
    }
    
    admin = request.user.groups.filter(name="reviewers-admins").exists()
    
    if key:
        ctx.update({
            "key": key,
            "proposals": proposals_generator(request, proposals[key], check_speaker=not admin),
            "proposal_count": proposals[key].count(),
        })
    else:
        ctx["proposals"] = proposals
    
    return render(request, "reviews/review_stats.html", ctx)


@login_required
def review_assignments(request):
    if not request.user.groups.filter(name="reviewers").exists():
        return access_not_permitted(request)
    assignments = ReviewAssignment.objects.filter(
        user=request.user,
        opted_out=False
    )
    return render(request, "reviews/review_assignment.html", {
        "assignments": assignments,
    })


@login_required
@require_POST
def review_assignment_opt_out(request, pk):
    review_assignment = get_object_or_404(ReviewAssignment,
        pk=pk,
        user=request.user
    )
    if not review_assignment.opted_out:
        review_assignment.opted_out = True
        review_assignment.save()
        ReviewAssignment.create_assignments(review_assignment.proposal, origin=ReviewAssignment.AUTO_ASSIGNED_LATER)
    return redirect("review_assignments")


@login_required
def review_bulk_accept(request):
    if not request.user.groups.filter(name="reviewers-admins").exists():
        return access_not_permitted(request)
    if request.method == "POST":
        form = BulkPresentationForm(request.POST)
        if form.is_valid():
            talk_ids = form.cleaned_data["talk_ids"].split(",")
            talks = ProposalBase.objects.filter(id__in=talk_ids).select_related("result")
            for talk in talks:
                talk.result.accepted = True
                talk.result.save()
            return redirect("review_list")
    else:
        form = BulkPresentationForm()
    
    return render(request, "reviews/review_bulk_accept.html", {
        "form": form,
    })
